from fastmcp import FastMCP
import server.grocery_services as grocery_services
import server.calendar_services as calendar_services
from server.llm import llm_service

mcp = FastMCP("Telegram Bot Server")

# Grocery Tools
mcp.tool(grocery_services.get_grocery_list)
mcp.tool(grocery_services.add_to_grocery_list)
mcp.tool(grocery_services.delete_grocery_list)
mcp.tool(grocery_services.merge_grocery_lists)
mcp.tool(grocery_services.add_grocery_share_request)
mcp.tool(grocery_services.get_grocery_share_request)
mcp.tool(grocery_services.update_grocery_share_request_status)

# Calendar Tools
mcp.tool(calendar_services.get_calendar_event_by_id)
mcp.tool(calendar_services.get_calendar_events)
mcp.tool(calendar_services.search_calendar_events)
mcp.tool(calendar_services.create_calendar_event)
mcp.tool(calendar_services.delete_calendar_event)

# LLM Tools
mcp.tool(llm_service.extract_text_from_image)
mcp.tool(llm_service.transcribe_audio)
mcp.tool(llm_service.get_chat_response)
mcp.tool(llm_service.classify_intent_and_extract_params)
mcp.tool(llm_service.parse_date_range_llm)
mcp.tool(llm_service.extract_event_details_llm)
mcp.tool(llm_service.find_event_match_llm)
mcp.tool(llm_service.extract_read_args_llm)
mcp.tool(llm_service.extract_search_args_llm)
mcp.tool(llm_service.extract_create_args_llm)

if __name__ == "__main__":
    mcp.run()
