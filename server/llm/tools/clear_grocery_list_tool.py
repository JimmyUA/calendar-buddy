import logging
import asyncio
from typing import Type
from pydantic import BaseModel  # No specific args
from langchain.tools import BaseTool

logger = logging.getLogger(__name__)

class ClearGroceryListToolInput(BaseModel): # Optional
    pass

class ClearGroceryListTool(BaseTool):
    name: str = "clear_grocery_list"
    description: str = "Clears all items from the user's grocery list. Use with caution as this action is irreversible."
    args_schema: Type[BaseModel] = ClearGroceryListToolInput
    user_id: int
    user_timezone_str: str # Not used
    mcp_client: object

    def _run(self) -> str:
        return asyncio.run(self._arun())

    async def _arun(self) -> str:
        logger.info(f"ClearGroceryListTool: Called for user {self.user_id}")
        try:
            if await self.mcp_client.call_tool("delete_grocery_list", user_id=self.user_id):
                return "Successfully cleared your grocery list."
            else:
                return "Failed to clear the grocery list due to a service error."
        except Exception as e:
            logger.error(
                f"Error in ClearGroceryListTool for user {self.user_id}: {e}",
                exc_info=True,
            )
            return "An unexpected error occurred while trying to clear the grocery list."
