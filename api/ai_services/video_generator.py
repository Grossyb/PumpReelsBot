from abc import ABC, abstractmethod
import asyncio
import logging

logger = logging.getLogger(__name__)

class VideoGenerator(ABC):
    """
    Abstract base class for AI-powered video generation services.
    Any AI video provider (e.g., RunwayML, Stable Diffusion) should inherit from this.
    """

    @abstractmethod
    async def create_video(self, image_data: str, prompt_text: str, duration: int = 5) -> str:
        """
        Generates a video from an image and text prompt.
        :param image_data: Base64-encoded image
        :param prompt_text: Description for AI to generate video
        :param duration: Video duration in seconds (default: 5)
        :return: URL of the generated video or None if failed
        """
        pass

    @abstractmethod
    async def get_task_status(self, task_id: str) -> dict:
        """
        Polls the video generation task and retrieves its status.
        :param task_id: The ID of the AI task
        :return: A dictionary containing the task status and output URL if completed
        """
        pass

    async def poll_for_video(self, task_id: str) -> str:
        """
        Polls for the video generation task to complete.
        :param task_id: The ID of the AI task
        :return: The generated video URL or None if failed
        """
        while True:
            try:
                task = await self.get_task_status(task_id)
                status = task.get("status")

                if status == "SUCCEEDED":
                    return task.get("output")[0] if task.get("output") else None
                elif status in ["FAILED", "CANCELED"]:
                    logger.error(f"Video generation failed for task {task_id}")
                    return None

                logger.info(f"Task {task_id} still processing, waiting...")
            except Exception as e:
                logger.error(f"Error while polling task {task_id}: {e}")
                return None

            await asyncio.sleep(1)  # Wait before checking again
