import logging
from typing import Type
from pydantic import BaseModel # No specific args
from langchain.tools import BaseTool
import grocery_services as gs

logger = logging.getLogger(__name__)

class ClearGroceryListToolInput(BaseModel): # Optional
    pass

class ClearGroceryListTool(BaseTool):
    name: str = "clear_grocery_list"
    description: str = "Clears all items from the user's grocery list. Use with caution as this action is irreversible."
    args_schema: Type[BaseModel] = ClearGroceryListToolInput
    user_id: int
    user_timezone_str: str # Not used

    def _run(self) -> str:
        logger.info(f"ClearGroceryListTool: Called for user {self.user_id}")
        try:
            if gs.delete_grocery_list(self.user_id):
                return "Successfully cleared your grocery list."
            else:
                return "Failed to clear the grocery list due to a service error."
        except Exception as e:
            logger.error(f"Error in ClearGroceryListTool for user {self.user_id}: {e}", exc_info=True)
            return "An unexpected error occurred while trying to clear the grocery list."

    async def _arun(self) -> str:
        return self._run()
