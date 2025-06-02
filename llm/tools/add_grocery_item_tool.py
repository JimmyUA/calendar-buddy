import logging
from typing import Type, List
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
import google_services as gs # Assuming gs is accessible

logger = logging.getLogger(__name__)

class AddGroceryItemToolInput(BaseModel):
    items: str = Field(description="A comma-separated string of grocery items to add to the list. For example: 'milk, eggs, bread'")

class AddGroceryItemTool(BaseTool):
    name: str = "add_grocery_item"
    description: str = "Adds one or more items to the user's grocery list. Input should be a comma-separated string of items."
    args_schema: Type[BaseModel] = AddGroceryItemToolInput
    user_id: int # Set during instantiation
    user_timezone_str: str # Set during instantiation, though not strictly needed for this tool

    def _run(self, items: str) -> str:
        logger.info(f"AddGroceryItemTool: Called for user {self.user_id} with items: {items}")
        if not items or not isinstance(items, str):
            return "Input error: Please provide items as a comma-separated string."

        # Simple parsing: split by comma and strip whitespace
        item_list = [item.strip() for item in items.split(',') if item.strip()]

        if not item_list:
            return "Input error: No valid items provided after parsing. Please provide items like 'milk, eggs'."

        try:
            if gs.add_to_grocery_list(str(self.user_id), item_list): # user_id converted to str
                return f"Successfully added: {', '.join(item_list)} to your grocery list."
            else:
                return "Failed to add items to the grocery list due to a service error."
        except Exception as e:
            logger.error(f"Error in AddGroceryItemTool for user {self.user_id}: {e}", exc_info=True)
            return "An unexpected error occurred while trying to add items."
    
    async def _arun(self, items: str) -> str:
        # For simplicity, using the sync version. Implement async if gs calls are async.
        return self._run(items)
