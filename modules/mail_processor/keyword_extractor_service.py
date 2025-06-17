"""OpenRouter를 활용한 키워드 추출 서비스"""

import re
import time
import json
import aiohttp
from collections import Counter
from typing import List, Optional

from infra.core.config import get_config
from infra.core.logger import get_logger
from .mail_processor_schema import KeywordExtractionRequest, KeywordExtractionResponse


class MailProcessorKeywordExtractorService:
    """OpenRouter를 활용한 키워드 추출 서비스"""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger(__name__)

        # OpenRouter 설정
        self.api_key = getattr(self.config, "openrouter_api_key", None)
        self.model = getattr(self.config, "openrouter_model", "openai/gpt-3.5-turbo")
        self.base_url = "https://openrouter.ai/api/v1"

        # 재사용 가능한 세션 (클래스 레벨에서 관리)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self._session:
            await self._session.close()
            self._session = None

    async def close(self):
        """세션 수동 종료"""
        if self._session:
            await self._session.close()
            self._session = None

    async def extract_keywords(
        self, text: str, max_keywords: int = 5
    ) -> KeywordExtractionResponse:
        """메일 본문에서 키워드 추출"""
        start_time = time.time()

        try:
            # 텍스트 정제
            clean_text = self._clean_text(text)

            # 너무 짧은 텍스트는 빈 리스트 반환
            if len(clean_text.strip()) < 10:
                return KeywordExtractionResponse(
                    keywords=[],
                    method="empty_text",
                    model=self.model,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    token_info={},
                )

            # OpenRouter API 호출
            if self.api_key:
                keywords, token_info = await self._call_openrouter_api(
                    clean_text, max_keywords
                )
                if keywords:
                    self.logger.debug(f"키워드 추출 성공: {keywords}")
                    return KeywordExtractionResponse(
                        keywords=keywords,
                        method="openrouter",
                        model=self.model,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        token_info=token_info,
                    )

            # Fallback 키워드 추출
            keywords = self._fallback_keyword_extraction(clean_text, max_keywords)
            return KeywordExtractionResponse(
                keywords=keywords,
                method="fallback",
                model="rule_based",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_info={},
            )

        except Exception as e:
            self.logger.warning(f"키워드 추출 실패, fallback 사용: {str(e)}")
            keywords = self._fallback_keyword_extraction(text, max_keywords)
            return KeywordExtractionResponse(
                keywords=keywords,
                method="fallback_error",
                model="rule_based",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_info={},
            )

    async def _get_session(self) -> aiohttp.ClientSession:
        """세션 가져오기 (필요시 생성)"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _call_openrouter_api(
        self, text: str, max_keywords: int
    ) -> tuple[List[str], dict]:
        """OpenRouter API 호출"""

        # API 키 상태 확인
        if not self.api_key:
            self.logger.error("❌ OpenRouter API 키가 설정되지 않음")
            return [], {}

        # API 키 일부 표시 (디버깅용)
        self.logger.info(
            f"🔑 OpenRouter API 키: {self.api_key[:10]}...{self.api_key[-4:]}"
        )
        self.logger.info(f"📡 OpenRouter 모델: {self.model}")
        self.logger.info(f"🌐 OpenRouter URL: {self.base_url}/chat/completions")

        # 텍스트 길이 제한 (1000자로 줄임)
        limited_text = text[:1000] if len(text) > 1000 else text

        # 간단한 프롬프트
        prompt = f"Extract {max_keywords} keywords from this email: {limited_text}\n\nKeywords:"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter 공식 형식 - gpt-3.5-turbo는 더 안정적
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
            "temperature": 0.3,
        }

        # 토큰 정보 초기화
        token_info = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }

        self.logger.info(
            f"📤 요청 페이로드: {json.dumps(payload, ensure_ascii=False)[:200]}..."
        )

        session = None
        try:
            # 세션 가져오기
            session = await self._get_session()

            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:

                # 응답 상태 및 헤더 로그
                self.logger.info(f"📥 응답 상태: {response.status}")
                self.logger.info(f"📋 응답 헤더: {dict(response.headers)}")

                # 원시 응답 텍스트 먼저 읽기
                response_text = await response.text()
                self.logger.info(f"📄 원시 응답: {response_text[:500]}...")

                if response.status != 200:
                    self.logger.error(f"❌ API 오류: {response_text}")
                    return [], token_info

                # JSON 파싱
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    self.logger.error(f"❌ JSON 파싱 실패: {e}")
                    return [], token_info

                # 전체 응답 구조 로그
                self.logger.info(
                    f"📊 전체 응답 구조: {json.dumps(data, ensure_ascii=False, indent=2)}"
                )

                # 토큰 사용량 정보 추출
                if "usage" in data:
                    usage = data["usage"]
                    token_info.update(
                        {
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                        }
                    )

                    # 비용 계산 (gpt-3.5-turbo 기준: $0.0015/1K input, $0.002/1K output)
                    input_cost = (token_info["prompt_tokens"] / 1000) * 0.0015
                    output_cost = (token_info["completion_tokens"] / 1000) * 0.002
                    token_info["cost_usd"] = round(input_cost + output_cost, 6)

                # 응답에서 컨텐츠 추출
                if "choices" in data and data["choices"]:
                    choice = data["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        content = choice["message"]["content"]
                        self.logger.info(f"✅ 추출된 컨텐츠: '{content}'")

                        if content and content.strip():
                            keywords = self._parse_keywords(content)
                            self.logger.info(f"🏷️ 파싱된 키워드: {keywords}")
                            return keywords[:max_keywords], token_info
                        else:
                            self.logger.warning("⚠️ 컨텐츠가 비어있음")
                    else:
                        self.logger.error(f"❌ message.content 없음: {choice}")
                else:
                    self.logger.error(f"❌ choices 없음: {data}")

                return [], token_info

        except aiohttp.ClientError as e:
            self.logger.error(f"❌ 네트워크 오류: {str(e)}")
            return [], token_info
        except Exception as e:
            self.logger.error(f"❌ 예상치 못한 오류: {str(e)}", exc_info=True)
            return [], token_info

    def _fallback_keyword_extraction(self, text: str, max_keywords: int) -> List[str]:
        """OpenRouter 실패 시 간단한 fallback 키워드 추출"""
        # 간단한 한국어 단어 추출
        clean_text = self._clean_text(text)

        # 한국어 단어 추출 (2글자 이상)
        korean_words = re.findall(r"[가-힣]{2,}", clean_text)

        # 영문 단어 추출 (3글자 이상)
        english_words = re.findall(r"[A-Za-z]{3,}", clean_text)

        # 숫자 포함 식별자 추출 (예: EA004, REQ-123)
        identifiers = re.findall(r"[A-Z]{2,}\d+|[A-Z]+-\d+|\d{3,}", clean_text)

        # 모든 단어 합치기
        all_words = korean_words + english_words + identifiers

        # 빈도수 기반 상위 키워드 선택
        word_counts = Counter(all_words)
        top_keywords = [word for word, count in word_counts.most_common(max_keywords)]

        return top_keywords

    def _clean_text(self, text: str) -> str:
        """텍스트 정제 - 개선된 버전"""
        if not text:
            return ""

        # 1. 먼저 모든 종류의 줄바꿈을 일반 줄바꿈으로 통일
        # \r\n -> \n, \r -> \n
        clean = text.replace("\r\n", "\n")
        clean = clean.replace("\r", "\n")

        # 2. HTML 태그 제거
        clean = re.sub(r"<[^>]+>", "", clean)

        # 3. 이메일 주소를 공백으로 변환 (< > 안의 내용 포함)
        clean = re.sub(r"<[^>]+@[^>]+>", " ", clean)
        clean = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", " ", clean)

        # 4. URL 제거
        clean = re.sub(r"https?://[^\s]+", " ", clean)
        clean = re.sub(r"www\.[^\s]+", " ", clean)

        # 5. 연속된 줄바꿈을 하나의 공백으로 변환
        clean = re.sub(r"\n+", " ", clean)

        # 6. 탭 문자를 공백으로 변환
        clean = clean.replace("\t", " ")

        # 7. 특수문자 정리 (한글, 영문, 숫자, 기본 구두점만 유지)
        # 괄호, 하이픈, 콜론, 세미콜론도 추가로 유지
        clean = re.sub(r"[^\w\s가-힣.,!?():;-]", " ", clean)

        # 8. 불필요한 구분선 제거 (------, ====== 등)
        clean = re.sub(r"[-=]{3,}", " ", clean)

        # 9. 과도한 공백 정리
        clean = re.sub(r"\s+", " ", clean)

        # 10. 의미없는 단일 문자 제거 (단, 숫자는 유지)
        clean = re.sub(r"\b[a-zA-Z]\b", "", clean)

        # 11. 양쪽 공백 제거
        clean = clean.strip()

        return clean

    def _parse_keywords(self, content: str) -> List[str]:
        """다양한 형식의 키워드 응답을 파싱"""
        keywords = []

        self.logger.debug(f"키워드 파싱 시작: '{content}'")

        # 1. 번호 매김 형식: "1. 키워드1\n2. 키워드2\n3. 키워드3"
        if re.search(r"\d+\.\s*", content):
            self.logger.debug("번호 매김 형식으로 파싱")
            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # "1. 키워드" 형식에서 키워드만 추출
                match = re.match(r"\d+\.\s*(.+)", line)
                if match:
                    keyword = match.group(1).strip()
                    if keyword:
                        keywords.append(keyword)
                        self.logger.debug(f"번호 매김에서 추출: '{keyword}'")

        # 2. 콤마로 구분된 형식: "키워드1, 키워드2, 키워드3"
        elif "," in content:
            self.logger.debug("콤마 구분 형식으로 파싱")
            keywords = [kw.strip() for kw in content.split(",") if kw.strip()]

        # 3. 줄바꿈으로 구분된 형식: "키워드1\n키워드2\n키워드3"
        elif "\n" in content:
            self.logger.debug("줄바꿈 구분 형식으로 파싱")
            keywords = [line.strip() for line in content.split("\n") if line.strip()]

        # 4. 공백으로 구분된 형식: "키워드1 키워드2 키워드3"
        else:
            self.logger.debug("공백 구분 형식으로 파싱")
            keywords = content.split()

        # 키워드 정제
        cleaned_keywords = []
        for kw in keywords:
            # 불필요한 문자 제거 (앞뒤 특수문자)
            kw = re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", kw)
            # 최소 길이 확인 (2글자 이상)
            if kw and len(kw) >= 2:
                cleaned_keywords.append(kw)
                self.logger.debug(f"정제된 키워드: '{kw}'")

        self.logger.debug(f"최종 파싱 결과: {cleaned_keywords}")
        return cleaned_keywords
