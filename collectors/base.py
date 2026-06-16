"""采集器基类 - 架构专家：统一接口设计"""
import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """所有采集器的基类"""

    def __init__(self, name: str):
        self.name = name
        self._last_data_time: Optional[str] = None

    @abstractmethod
    def fetch(self) -> Any:
        """采集数据的主入口"""
        ...

    def safe_fetch(self) -> Optional[Any]:
        """带异常安全的采集包装 - 运维专家：永不抛异常到上层"""
        try:
            data = self.fetch()
            if data is not None:
                logger.info(f"[{self.name}] 采集成功")
            else:
                logger.warning(f"[{self.name}] 采集返回空")
            return data
        except Exception as e:
            logger.error(f"[{self.name}] 采集异常: {e}", exc_info=True)
            return None

    def get_status(self) -> Dict:
        """采集器状态"""
        return {
            "name": self.name,
            "last_data_time": self._last_data_time,
        }
