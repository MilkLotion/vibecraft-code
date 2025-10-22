__author__ = "Se Hoon Kim(sehoon787@korea.ac.kr)"

# Standard imports
import asyncio

# Third-party imports
from dotenv import load_dotenv

# Custom imports
from mcp_agent.client import VibeCraftClient

load_dotenv()


async def main():
    # print("✅ 사용할 AI 모델을 선택하세요: claude / gemini / gpt (기본: claude)")
    # engine = input("모델: ").strip().lower() or "claude"
    engine = "gemini"
    client = VibeCraftClient(engine)

    try:
        topic = input("🎤 주제를 입력하세요: ").strip()
        file = input("🎤 파일 경로를 입력하세요: ").strip()

        # topic = "서울시를 기준으로 음식 분류별 맛집 리스트를 시각화하는 페이지를 만들어줘"
        # file = r"./samples/dining.csv"

        await client.run_pipeline(topic, file)
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
