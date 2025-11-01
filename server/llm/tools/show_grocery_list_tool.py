import logging
import asyncio
from typing import Type
from pydantic import BaseModel  # No specific args needed for this tool
from langchain.tools import BaseTool

logger = logging.getLogger(__name__)

class ShowGroceryListToolInput(BaseModel): # Optional, but good practice for consistency
    pass 

class ShowGroceryListTool(BaseTool):
    name: str = "show_grocery_list"
    description: str = "Shows all items currently on the user's grocery list."
    args_schema: Type[BaseModel] = ShowGroceryListToolInput
    user_id: int
    user_timezone_str: str # Not used, but part of the pattern
    mcp_client: object

    def _run(self) -> str:
        return asyncio.run(self._arun())

    async def _arun(self) -> str:
        logger.info(f"ShowGroceryListTool: Called for user {self.user_id}")
        try:
            grocery_list = await self.mcp_client.call_tool("get_grocery_list", user_id=self.user_id)
            if grocery_list is None:
                return "Error: Could not retrieve the grocery list at the moment."
            elif not grocery_list:
                return "Your grocery list is currently empty."
            else:
                return f"Your grocery list: {', '.join(grocery_list)}."
        except Exception as e:
            logger.error(
                f"Error in ShowGroceryListTool for user {self.user_id}: {e}",
                exc_info=True,
            )
            return "An unexpected error occurred while trying to show the grocery list."
