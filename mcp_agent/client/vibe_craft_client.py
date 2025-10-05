__author__ = "Se Hoon Kim(sehoon787@korea.ac.kr)"

# Standard imports
import os
from typing import Dict, Any

# Third-party imports
from langchain_mcp_adapters.client import MultiServerMCPClient

# Custom imports
from mcp_agent.client import VibeCraftAgentRunner
from mcp_agent.engine import (
    ClaudeEngine,
    OpenAIEngine,
    GeminiEngine
)
from mcp_agent.schemas.prompt_parser_schemas import VisualizationType
from mcp_agent.schemas import (
    MCPServerConfig,
    VisualizationRecommendationResponse
)
from utils import FileUtils, PathUtils
from utils.prompts import *


class VibeCraftClient:
    def __init__(self, engine: str):
        if engine == "claude":
            self.engine = ClaudeEngine()
        elif engine == "gemini":
            self.engine = GeminiEngine()
        elif engine == "gpt":
            self.engine = OpenAIEngine()
        else:
            raise ValueError("Not Supported Engine")
        self.client: Optional[MultiServerMCPClient] = None

        self.mcp_tools: Optional[List[MCPServerConfig]] = None  # common MCP tools
        self.topic_mcp_server: Optional[List[MCPServerConfig]] = None
        self.set_data_mcp_server: Optional[List[MCPServerConfig]] = None  # TODO: WIP

        self.tools: Optional[List] = None

        self.data: Optional[pd.DataFrame] = None

    """Engine Methods"""
    def get_thread_id(self) -> str:
        return str(self.engine.thread_id)

    def merge_chat_history(self, thread_id: str):
        self.engine.merge_chat_history(thread_id=thread_id)

    def load_chat_history(self, thread_id: str):
        self.engine.load_chat_history(thread_id=thread_id)

    async def load_tools(self, mcp_servers: Optional[List[MCPServerConfig]] = None):
        """
        Connect Multiple MCP servers with ClientSessionGroup, and integrate tools, prompts, resources.
        Save self.session
        """

        mcp_servers = mcp_servers or self.mcp_tools
        if mcp_servers:
            try:
                self.client = MultiServerMCPClient(
                    {
                        tool.name: {
                            "command": tool.command,
                            "args": tool.args,
                            "transport": tool.transport
                        }
                        for tool in mcp_servers
                    }
                )
                self.tools = await self.client.get_tools()
                self.engine.update_tools(self.tools)
                print(f"\n🔌 Connected to {', '.join([t.name for t in mcp_servers])}")
                print("Connected to server with tools:", [tool.name for tool in self.tools])
            except Exception as e:
                print(f"⚠️ 서버 연결 실패: {', '.join([t.name for t in mcp_servers])} - {e}")

    async def execute_step(
        self, prompt: str, system: Optional[str] = None,
        use_langchain: Optional[bool] = True,
    ) -> str:
        if use_langchain:
            return await self.engine.generate_langchain(prompt=prompt, system=system)
        return await self.engine.generate(prompt=prompt)

    def get_summary(self) -> str:
        stats = self.engine.get_conversation_stats()
        if stats['has_summary']:
            return stats["summary"]
        else:
            self.engine.trigger_summarize()
            stats = self.engine.get_conversation_stats()
            return stats["summary"]

    """Topic Selection Methods"""
    async def topic_selection(self, topic_prompt: str) -> str:
        """Step 1: 주제 설정"""
        await self.load_tools(self.topic_mcp_server)

        print("\n🚦 Step 1: 주제 설정")
        system, human = set_topic_prompt(topic_prompt)
        result = await self.execute_step(human, system)
        print(result)
        return result

    """Data loading and generation Methods"""
    async def set_data(self, file_path: Optional[str] = None) -> pd.DataFrame:
        """Step 2: 데이터 업로드 또는 생성"""
        print("\n🚦 Step 2: 데이터 업로드")
        await self.load_tools(self.set_data_mcp_server)

        if file_path:
            self.data = FileUtils.load_local_files([file_path])
        else:
            self.data = FileUtils.load_files()

        # 데이터 자동 전처리 및 저장
        await self.auto_process_and_save_data()

        return self.data

    """Data processing Methods"""
    async def auto_process_and_save_data(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Step 3: 데이터 자동 전처리 및 저장 (단일 프롬프트)"""
        if df is None:
            df = self.data

        print("\n🚦 Step 3: 데이터 자동 전처리 및 저장")

        # 1. 데이터 전처리
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        df.columns = [FileUtils.normalize_column_name(col) for col in df.columns]
        print(f"\n📊 데이터프레임 정제 완료:\n{df.head(3).to_string(index=False)}")

        # 2. 단일 프롬프트로 컬럼 삭제 + 영문 변환 한번에 처리
        print("\n🧹 불필요한 컬럼 제거 및 영문 변환 중...")
        system, human = auto_process_data_prompt(df)
        result = await self.execute_step(human, system)
        print(f"\n🤖 Agent 처리 결과:\n{result}")

        # 3. 결과 파싱 및 적용
        new_col = FileUtils.parse_dict_flexible(result)
        filtered_new_col = {k: v for k, v in new_col.items() if v is not None}

        # 컬럼 매핑 적용 (dictionary에 없는 컬럼은 자동 제거됨)
        mapped_df = df.rename(columns=new_col)[list(filtered_new_col.values())]
        print(f"\n🧱 최종 데이터:\n{mapped_df.head(3).to_string(index=False)}")

        # 4. 파일 저장
        path = PathUtils.generate_path(self.get_thread_id())
        mapped_df.to_csv(os.path.join(path, f"{self.get_thread_id()}.csv"), encoding="cp949", index=False)
        file_path = FileUtils.save_sqlite(mapped_df, path, self.get_thread_id())
        FileUtils.save_metadata(filtered_new_col, path, file_path)
        self.data = mapped_df

        return mapped_df

    """Code Generator Methods"""
    async def auto_recommend_visualization_type(self) -> VisualizationType:
        """Step 4: 시각화 타입 자동 결정"""
        print("\n🚦 Step 4: 시각화 타입 자동 결정")

        stats = self.engine.get_conversation_stats()
        if stats['has_summary']:
            user_context = stats["summary"]
        else:
            self.engine.trigger_summarize()
            stats = self.engine.get_conversation_stats()
            user_context = stats["summary"]

        system, human = recommend_visualization_template_prompt(self.data, user_context)
        result = await self.execute_step(human, system)

        recommendations = FileUtils.parse_visualization_recommendation(result)
        response = VisualizationRecommendationResponse(
            user_context=user_context,
            recommendations=recommendations
        )

        # 가장 신뢰도 높은 시각화 타입 자동 선택
        top_recommendation = response.get_top_recommendation()
        print(f"💡 자동 선택된 시각화 타입: {top_recommendation.visualization_type} (신뢰도: {top_recommendation.confidence}%)")

        return top_recommendation.visualization_type

    def run_code_generator(
            self, thread_id: str, visualization_type: VisualizationType,
            project_name: str = None, model: str = "pro"
    ) -> Dict[str, Any]:
        """동기 방식 코드 생성"""
        print("\n🚦 Step 5: 웹앱 코드 생성")

        runner = VibeCraftAgentRunner()
        file_name = f"{thread_id}.sqlite"

        if not runner.is_available() or not PathUtils.is_exist(thread_id, file_name):
            return {"success": False, "message": "전제 조건 확인 실패"}

        file_path = PathUtils.get_path(thread_id, file_name)[0]
        output_dir = f"./output/{thread_id}"

        try:
            result = runner.run_agent(
                sqlite_path=file_path,
                visualization_type=visualization_type,
                user_prompt=self.get_summary(),
                output_dir=output_dir,
                project_name=project_name or f"vibecraft-{thread_id}",
                model=model
            )

            if result["success"]:
                print(f"✅ 코드 생성 완료: {result['output_dir']}")

            return result
        except Exception as e:
            return {"success": False, "message": str(e)}

    """Pipeline"""
    async def run_pipeline(self, topic_prompt: str, file_path: str):
        """
        간소화된 자동 파이프라인

        Args:
            topic_prompt: 분석 주제
            file_path: 데이터 파일 경로
        """
        # Step 1: 주제 설정
        await self.topic_selection(topic_prompt)

        # Step 2: 데이터 업로드 또는 생성
        await self.set_data(file_path)

        # 이후 자동화 프로세스
        # Step 4: 인과관계 분석 (BaseEngine에서 자동으로 RAG 활용)
        print("\n🚦 Step 4: 데이터 인과관계 분석")
        analysis_query = f"다음 데이터의 인과관계를 분석해주세요:\n{self.data.head(10).to_string()}"
        analysis_result = await self.execute_step(analysis_query)
        print(f"\n📊 인과관계 분석 결과:\n{analysis_result}")

        # Step 5: 시각화 타입 자동 결정
        v_type = await self.auto_recommend_visualization_type()

        # Step 6: 코드 자동 생성
        print(f"\n💻 시각화 타입 '{v_type}'으로 코드 생성을 진행합니다...")
        result = self.run_code_generator(self.get_thread_id(), v_type)

        if result["success"]:
            print(f"\n✅ 파이프라인 완료! 생성된 코드: {result['output_dir']}")
            return result
        else:
            print(f"\n❌ 코드 생성 실패: {result['message']}")
            return result

    async def chat_loop(self):
        """
        대화형 채팅 루프
        사용자가 '종료', 'exit', 'quit' 등을 입력하면 종료됩니다.
        """
        print("\n💬 채팅 모드를 시작합니다.")
        print("💡 종료하려면 '종료', 'exit', 'quit' 중 하나를 입력하세요.\n")

        # MCP 도구 로드 (선택사항 - 필요에 따라 주석 해제)
        # await self.load_tools(self.mcp_tools)

        exit_commands = ['종료', 'exit', 'quit', '나가기', 'q']

        while True:
            try:
                user_input = input("🎤 사용자: ").strip()

                # 종료 명령 체크
                if user_input.lower() in exit_commands:
                    print("\n👋 채팅을 종료합니다.")
                    break

                # 빈 입력 체크
                if not user_input:
                    print("⚠️ 메시지를 입력해주세요.")
                    continue

                # AI 응답 생성
                response = await self.execute_step(user_input)
                print(f"\n🤖 AI: {response}\n")

                # 대화 기록 저장
                self.engine.save_chat_history()

            except KeyboardInterrupt:
                print("\n\n👋 Ctrl+C를 감지했습니다. 채팅을 종료합니다.")
                break
            except Exception as e:
                print(f"\n❌ 오류 발생: {e}")
                print("계속 진행하시겠습니까? (y/n): ", end="")
                continue_choice = input().strip().lower()
                if continue_choice != 'y':
                    break

        print("✅ 채팅이 종료되었습니다.")

    async def test(self):
        print("🔥 Run Test...")
        prompt = "주제를 자동으로 설정해줘"

        # Run without Langchain
        result0 = await self.execute_step(prompt, use_langchain=False)
        print(f"\n🤖 Run without tool and Langchain:\n{result0}\n")

        # Run Langchain
        result1 = await self.execute_step(prompt)
        print(f"\n🤖 Langchain without tool:\n{result1}\n")

        while True:
            query = input("\n사용자: ").strip()
            result = await self.execute_step(query)
            print(result)

            self.engine.save_chat_history()
            self.merge_chat_history(thread_id="0d11b676-9cc5-4eb2-a90e-59277ca590fa")
            self.load_chat_history(thread_id="0d11b676-9cc5-4eb2-a90e-59277ca590fa")

    async def cleanup(self):
        self.client = None
