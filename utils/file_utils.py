__author__ = "Se Hoon Kim(sehoon787@korea.ac.kr)"

# Standard imports
import os
import json
import re
import sqlite3
import ast
from typing import List, Optional
from datetime import datetime

# Third-party imports
import pandas as pd
import chardet

# Custom imports
from mcp_agent.schemas import (
    VisualizationType,
    VisualizationRecommendation
)


class FileUtils:
    """파일 처리 관련 유틸리티 클래스"""

    @staticmethod
    def load_files() -> pd.DataFrame:
        """사용자 입력을 받아 파일을 로드합니다."""
        print("\n📁 CSV 또는 SQLite 파일 경로를 입력하세요. 쉼표(,)로 여러 개 입력 가능합니다.")
        file_input = input("파일 경로들: ").strip()
        paths = [path.strip() for path in file_input.split(",")]
        return FileUtils.load_local_files(paths)

    @staticmethod
    def detect_file_encoding(path: str, num_bytes: int = 10000) -> str:
        """파일의 인코딩을 감지합니다."""
        with open(path, 'rb') as f:
            raw_data = f.read(num_bytes)
        result = chardet.detect(raw_data)
        return result['encoding'] or 'utf-8'

    @staticmethod
    def load_local_files(file_paths: List[str]) -> Optional[pd.DataFrame]:
        """로컬 파일들을 로드하여 하나의 DataFrame으로 합칩니다."""
        dataframes = []
        for path in file_paths:
            if not os.path.exists(path):
                print(f"❌ 파일 없음: {path}")
                continue
            try:
                if path.endswith(".csv"):
                    encoding = FileUtils.detect_file_encoding(path)
                    df_part = pd.read_csv(path, encoding=encoding)
                elif path.endswith(".sqlite") or path.endswith(".db"):
                    with sqlite3.connect(path) as conn:
                        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table';", conn)
                        table_name = tables['name'].iloc[0]
                        df_part = pd.read_sql(f"SELECT * FROM {table_name}", conn)
                else:
                    print(f"⚠️ 지원되지 않는 파일 형식: {path}")
                    continue
                dataframes.append(df_part)
            except Exception as e:
                print(f"⚠️ 오류 발생: {e} (파일: {path})")

        if dataframes:
            return pd.concat(dataframes, ignore_index=True)
        return None

    @staticmethod
    def markdown_table_to_df(text: str) -> Optional[pd.DataFrame]:
        """마크다운 테이블 텍스트를 DataFrame으로 변환합니다."""
        try:
            # 텍스트에서 마크다운 테이블 부분만 추출
            lines = text.strip().split('\n')

            # 테이블 시작과 끝 찾기
            table_lines = []
            in_table = False

            for line in lines:
                line = line.strip()
                if '|' in line:
                    if not in_table:
                        in_table = True
                        table_lines.append(line)
                    elif '---' in line:  # 구분선은 건너뛰기
                        continue
                    else:
                        table_lines.append(line)
                elif in_table:
                    # 테이블이 끝났으면 중단
                    break

            if len(table_lines) < 2:
                raise ValueError("유효한 테이블을 찾을 수 없습니다.")

            # 파이프 정리 및 데이터 준비
            cleaned_lines = []
            for line in table_lines:
                # 양쪽 끝 파이프 제거 및 내부 파이프로 분할
                if line.startswith('|'):
                    line = line[1:]
                if line.endswith('|'):
                    line = line[:-1]

                # 셀들을 분할하고 공백 제거
                cells = [cell.strip() for cell in line.split('|')]
                cleaned_lines.append(cells)

            # DataFrame 생성
            if len(cleaned_lines) > 0:
                headers = cleaned_lines[0]
                data = cleaned_lines[1:] if len(cleaned_lines) > 1 else []

                # 모든 행의 컬럼 수를 헤더와 맞추기
                for i, row in enumerate(data):
                    if len(row) < len(headers):
                        data[i].extend([''] * (len(headers) - len(row)))
                    elif len(row) > len(headers):
                        data[i] = row[:len(headers)]

                df = pd.DataFrame(data, columns=headers)

                # 빈 행 제거
                df = df.dropna(how='all').reset_index(drop=True)

                print(f"✅ 성공적으로 파싱됨: {len(df)} 행, {len(df.columns)} 컬럼")
                return df
            else:
                raise ValueError("테이블 데이터가 없습니다.")

        except Exception as e:
            print(f"⚠️ 샘플 데이터 파싱 오류: {e}")
            print(f"원본 텍스트 일부:\n{text[:500]}...")
            return None

    @staticmethod
    def normalize_column_name(col: str) -> str:
        """컬럼명을 정규화합니다."""
        return col.strip().replace("\u200b", "").replace("\xa0", "").replace("\t", "").replace("\n", "").replace("\r",
                                                                                                                 "")

    @staticmethod
    def parse_first_row_dict_from_text(response_text: str) -> dict:
        """LLM 응답의 첫 줄에서 컬럼명 매핑 dict만 파싱합니다."""
        first_line = response_text.strip().splitlines()[0]
        try:
            mapping = ast.literal_eval(first_line)
            if isinstance(mapping, dict):
                return mapping
            else:
                raise ValueError("파싱된 결과가 dict가 아닙니다.")
        except Exception as e:
            raise ValueError(f"컬럼 매핑 파싱 실패: {e}")

    @staticmethod
    def save_metadata(col_info: dict, save_path: str, sqlite_path: str):
        """메타데이터를 JSON 파일로 저장합니다."""
        base_name = os.path.splitext(os.path.basename(sqlite_path))[0]
        meta_path = os.path.join(save_path, f"{base_name}_meta.json")

        metadata = {
            "created_at": datetime.now().isoformat(),
            "column_mapping": col_info
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        print(f"✅ DB 메타데이터 저장 완료: {meta_path}")

    @staticmethod
    def save_sqlite(df: pd.DataFrame, save_path: str, file_name: str) -> str:
        """
        DataFrame을 SQLite 파일로 저장하고, 저장된 파일 경로를 반환합니다.
        파일명은 현재 시각 기반으로 자동 생성됩니다.
        """
        file_path = os.path.join(save_path, f"{file_name}.sqlite")
        table_name = "data"  # 기본 테이블명

        with sqlite3.connect(file_path) as conn:
            df.to_sql(table_name, conn, index=False, if_exists="replace")

        print(f"✅ SQLite 파일 저장 완료: {file_path}")
        return file_path

    @staticmethod
    def parse_visualization_recommendation(
            llm_response: str
    ) -> List[VisualizationRecommendation]:
        """
        LLM 응답에서 시각화 추천 정보를 파싱합니다.

        Args:
            llm_response (str): LLM의 응답 텍스트

        Returns:
            List[VisualizationRecommendation]: 파싱된 추천 목록

        Raises:
            ValueError: JSON 파싱 실패 또는 데이터 검증 실패시
            json.JSONDecodeError: JSON 형식이 올바르지 않을 때
        """
        try:
            # JSON 코드 블록에서 JSON 부분만 추출
            json_match = re.search(r'```json\s*(\[.*?\])\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 코드 블록이 없는 경우 전체 응답에서 JSON 배열 찾기
                json_match = re.search(r'(\[.*?\])', llm_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    raise ValueError("응답에서 JSON 형식을 찾을 수 없습니다")

            # JSON 파싱
            parsed_data = json.loads(json_str)

            # 단일 객체인 경우 리스트로 변환
            if isinstance(parsed_data, dict):
                parsed_data = [parsed_data]

            # 데이터 변환 및 검증
            recommendations = [VisualizationRecommendation(**item) for item in parsed_data]
            return recommendations

        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"JSON 파싱 실패: {str(e)}", e.doc, e.pos)
        except Exception as e:
            raise ValueError(f"데이터 파싱 실패: {str(e)}")
