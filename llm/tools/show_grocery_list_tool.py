import logging
from typing import Type
from pydantic import BaseModel # No specific args needed for this tool
from langchain.tools import BaseTool
import google_services as gs

logger = logging.getLogger(__name__)

class ShowGroceryListToolInput(BaseModel): # Optional, but good practice for consistency
    pass 

class ShowGroceryListTool(BaseTool):
    name: str = "show_grocery_list"
    description: str = "Shows all items currently on the user's primary grocery list."
    args_schema: Type[BaseModel] = ShowGroceryListToolInput
    user_id: int
    user_timezone_str: str # Not used, but part of the pattern

    def _run(self) -> str:
        logger.info(f"ShowGroceryListTool: Called for user {self.user_id}")
        try:
            # gs.get_grocery_list is expected to return items from the user's owned list.
            grocery_list_items = gs.get_grocery_list(str(self.user_id)) # user_id converted to str
            if grocery_list_items is None:
                # This condition might indicate an actual error in service layer if it's not supposed to return None for "no list found"
                return "Error: Could not retrieve your primary grocery list at the moment."
            elif not grocery_list_items:
                return "Your primary grocery list is currently empty."
            else:
                return f"Your primary grocery list contains: {', '.join(grocery_list_items)}."
        except Exception as e:
            logger.error(f"Error in ShowGroceryListTool for user {self.user_id}: {e}", exc_info=True)
            return "An unexpected error occurred while trying to show the grocery list."

    async def _arun(self) -> str:
        return self._run()
