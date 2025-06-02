import logging
from typing import Type
from pydantic import BaseModel # No specific args
from langchain.tools import BaseTool
import google_services as gs

logger = logging.getLogger(__name__)

class ClearGroceryListToolInput(BaseModel): # Optional
    pass

class ClearGroceryListTool(BaseTool):
    name: str = "clear_grocery_list"
    description: str = "Clears all items from the user's primary grocery list. Use with caution as this action is irreversible."
    args_schema: Type[BaseModel] = ClearGroceryListToolInput
    user_id: int
    user_timezone_str: str # Not used

    def _run(self) -> str:
        logger.info(f"ClearGroceryListTool: Called for user {self.user_id}")
        try:
            # Call clear_grocery_list_items, passing user_id as string and list_id=None for owned list
            if gs.clear_grocery_list_items(str(self.user_id), list_id=None):
                return "Successfully cleared items from your primary grocery list."
            else:
                # This could mean no owned list was found, or an error occurred.
                # gs.clear_grocery_list_items logs details.
                return "Failed to clear items from the grocery list. You might not have an owned list or a service error occurred."
        except Exception as e:
            logger.error(f"Error in ClearGroceryListTool for user {self.user_id}: {e}", exc_info=True)
            return "An unexpected error occurred while trying to clear the grocery list."

    async def _arun(self) -> str:
        return self._run()
