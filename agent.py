# agent.py
import logging
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
from agent_tools import get_tools

logger = logging.getLogger(__name__)

# === Agent Initialization (Helper) ===

def initialize_agent(user_id: int, user_timezone_str: str, chat_history: list) -> AgentExecutor:
    """Initializes and returns a LangChain agent executor for the user."""

    # 1. Initialize LLM
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro-preview-03-25", temperature=0.1, convert_system_message_to_human=True)
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
    Thought: you should always think about what to do to fulfill the user's request. If the request involves specific calendar actions, identify the correct tool and the necessary natural language input for it based on the conversation. If searching before deleting, note the event ID returned by the search tool.
    Action: the action to take, should be one of [{", ".join([t.name for t in tools])}]
    Action Input: The natural language query or description needed by the tool (e.g., for 'read_calendar_events', provide 'tomorrow'; for 'create_calendar_event', provide 'Meeting with Bob 3pm'; for 'search_calendar_events', provide 'project alpha meeting'; for 'delete_calendar_event', provide the specific event ID from a previous search). Do NOT provide JSON or structured data here, just the text input for the tool.
    Observation: the result of the action
    ... (this Thought/Action/Action Input/Observation can repeat N times)
    Thought: I now know the final answer based on the tool usage or conversation.
    Final Answer: the final answer to the original input question

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
        role = msg.get("role"); content = msg.get("content", "")
        if role == "user": memory_messages.append(HumanMessage(content=content))
        elif role == "model": memory_messages.append(AIMessage(content=content))

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
    )

    return agent_executor