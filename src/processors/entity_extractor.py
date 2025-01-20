import logging

from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EntityExtractor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=3600)
        self.pg_conn = None

    async def process(self):
        pass
