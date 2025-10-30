# agent.py
import logging
# Langchain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.agents.format_scratchpad.log import format_log_to_str
from langchain_classic.agents.output_parsers.react_single_input import ReActSingleInputOutputParser
from langchain_classic.agents.agent import AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage
from langchain_classic.memory.buffer_window import ConversationBufferWindowMemory
from langchain_core.chat_history import ChatMessageHistory
from langchain_core.tools import render_text_description

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
    Observation: the result of the action.
    **IMPORTANT:** If the Observation from 'create_calendar_event' or 'delete_calendar_event' is a question asking for confirmation (e.g., "Should I add this..." or "Should I delete this..."), your job is done for this step. Your Final Answer MUST be exactly that confirmation question. Do not try to call the tool again or re-answer the original question in this case.
    If the Observation is a formatted list of calendar events (e.g., from 'read_calendar_events' or 'search_calendar_events'), your Final Answer MUST be exactly that formatted list with no changes.
    ... (this Thought/Action/Action Input/Observation can repeat N times)
    Thought: I have the information needed OR the tool returned a confirmation question.
    Final Answer: the final answer to the original input question, OR the exact confirmation question returned by a tool.

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
        max_iterations=6,
    )

    return agent_executor
