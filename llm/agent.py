# agent.py
import logging
import base64 # Import base64 for image encoding
# Langchain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
# --> Import ReAct specific formatting helper <--
from langchain.agents.format_scratchpad.log import format_log_to_str # Try string format
# from langchain.agents.format_scratchpad.openai_functions import format_to_openai_function_messages # Alternative for function calling
from langchain.agents.output_parsers.react_single_input import ReActSingleInputOutputParser # Standard parser for ReAct

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate # Import PromptTemplate for string formatting
from langchain_core.messages import AIMessage, HumanMessage
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.chat_message_histories import ChatMessageHistory
# --> Import tool rendering helper <--
from langchain.tools.render import render_text_description

import config
from llm.agent_tools import get_tools

logger = logging.getLogger(__name__)

# === Agent Initialization (Helper) ===

def initialize_agent(user_id: int, user_timezone_str: str, chat_history: list) -> AgentExecutor:
    """Initializes and returns a LangChain agent executor for the user."""

    # 1. Initialize LLM
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-001", temperature=0.1, convert_system_message_to_human=True)
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {e}", exc_info=True); raise

    # 2. Get Tools with Context
    tools = get_tools(user_id=user_id, user_timezone_str=user_timezone_str)

    # 3. Create Prompt Template - Reverting to a more standard ReAct structure
    #    The core idea is to render tools into a string and have the LLM generate
    #    text including Thought/Action/Action Input blocks.
    #    The agent_scratchpad variable will contain the formatted log of previous steps.

    # Render tool descriptions into a string format
    tool_descriptions = render_text_description(tools)

    template = f"""
    Answer the following questions as best you can based on the conversation history and the user's request. You have access to the following tools:

    {tool_descriptions}

    Use the following format:

    Question: the input question you must answer
    Thought: Step-by-step thinking process. If deleting, first use 'search_calendar_events' to find the event ID. Then, use 'delete_calendar_event' with ONLY the event ID. If creating, use 'create_calendar_event' with the natural language description.
    Action: the action to take, one of [{", ".join([t.name for t in tools])}]
    Action Input: The required input for the action (natural language for create/read/search, event ID for delete).
    Observation: the result of the action. **IMPORTANT: If the Observation from 'create_calendar_event' or 'delete_calendar_event' is a question asking for confirmation (e.g., "Should I add this..." or "Should I delete this..."), your job is done for this step. Your Final Answer MUST be exactly that confirmation question.** Do not try to call the tool again or re-answer the original question in this case.
    ... (this Thought/Action/Action Input/Observation can repeat N times)
    Thought: I have the information needed OR the tool returned a confirmation question.
    Final Answer: the final answer to the original input question, OR the exact confirmation question returned by the create/delete tool.

    Begin!

    User's Timezone: {user_timezone_str}
    Previous conversation history:
    {{chat_history}}

    New input: {{input}}
    {{agent_scratchpad}}
    """

    prompt = PromptTemplate.from_template(template) # Use basic PromptTemplate for string formatting

    # 4. Create Agent Runnable
    # Bind stop sequence to LLM to make it stop generating after seeing "Observation:"
    # This helps the ReAct parser identify the end of an action step.
    llm_with_stop = llm.bind(stop=["\nObservation:"])

    agent = (
        {
            "input": lambda x: x["input"],
            "agent_scratchpad": lambda x: format_log_to_str(x["intermediate_steps"]), # Format steps into string scratchpad
            "chat_history": lambda x: x["chat_history"], # Pass history through
            # Render tools description into the prompt
            # Note: This might differ slightly based on exact LangChain version/agent type
            # We are manually putting it into the template string now.
        }
        | prompt
        | llm_with_stop
        | ReActSingleInputOutputParser() # Use the standard ReAct parser
    )


    # 5. Create Memory object
    memory_messages = []
    for msg in chat_history:
        role = msg.get("role")
        parts = msg.get("parts", [])
        langchain_message_content = []

        if not parts: # Should not happen if handlers.py is correct
            logger.warning(f"Encountered a message with no parts in chat_history: {msg}")
            # Fallback for old format or error: use 'content' if available
            content_fallback = msg.get("content")
            if content_fallback:
                langchain_message_content.append({'type': 'text', 'text': content_fallback})
            else:
                continue # Skip this message if no parts and no content

        for part in parts:
            part_type = part.get("type")
            if part_type == "text":
                langchain_message_content.append({"type": "text", "text": part.get("text", "")})
            elif part_type == "image":
                source = part.get("source", {})
                image_bytes = source.get("data")
                mime_type = source.get("media_type", "image/jpeg") # Default to jpeg
                if image_bytes and isinstance(image_bytes, bytes):
                    encoded_image = base64.b64encode(image_bytes).decode('utf-8')
                    langchain_message_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}
                    })
                else:
                    logger.warning(f"Image part missing data or data is not bytes: {part}")
            else:
                logger.warning(f"Unknown part type encountered: {part_type} in message: {msg}")

        if not langchain_message_content: # If after processing parts, content is still empty
            logger.warning(f"Message content is empty after processing parts for: {msg}")
            continue

        if role == "user":
            memory_messages.append(HumanMessage(content=langchain_message_content))
        elif role == "model":
            # For AIMessage, if content is just a single text string, pass it directly
            # Otherwise, pass the list of parts.
            # For now, model responses are text only, so this simplifies it.
            # If future AI responses are multimodal, this logic might need adjustment
            # based on how AIMessage handles lists of content parts.
            if len(langchain_message_content) == 1 and langchain_message_content[0]["type"] == "text":
                memory_messages.append(AIMessage(content=langchain_message_content[0]["text"]))
            else:
                # This case is for future-proofing if AI can send multiple parts (e.g. text and image)
                # Or if a text message was incorrectly structured as multiple text parts.
                memory_messages.append(AIMessage(content=langchain_message_content))

    k_turns = getattr(config, 'MAX_HISTORY_TURNS', 10)
    memory = ConversationBufferWindowMemory(
        memory_key="chat_history",
        chat_memory=ChatMessageHistory(messages=memory_messages),
        k=k_turns,
        return_messages=False, # Return history as a string for basic PromptTemplate
        input_key="input" # Define input key for memory
        )

    # 6. Create Agent Executor
    # IMPORTANT: AgentExecutor now takes the *runnable* agent directly, not create_react_agent result
    agent_executor = AgentExecutor(
        agent=agent, # Pass the runnable chain defined above
        tools=tools,
        memory=memory,
        verbose=True,
        handle_parsing_errors="Check your output and make sure it conforms to the ReAct format!",
        max_iterations=6,
    )

    return agent_executor