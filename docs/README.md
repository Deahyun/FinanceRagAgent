# Finance RAG Agent 초보자 문서

이 폴더는 **Finance RAG Agent** 를 처음 보는 사람을 위한 설명서입니다.
코드를 몰라도 “질문이 들어오면 무엇이 일어나는지”를 따라갈 수 있게 썼습니다.

개발자용 빠른 시작·기술 요약은 저장소 루트 [README.md](../README.md) 에 있습니다.

| 문서 | 내용 |
|------|------|
| [overview.md](overview.md) | 이 프로그램이 하는 일, 꼭 알아둘 단어 |
| [architecture.md](architecture.md) | 전체 구조와 질문이 처리되는 순서 |
| [files.md](files.md) | 폴더·파일마다 역할 (요약) |
| [getting-started.md](getting-started.md) | 설치하고 질문해 보기 (로컬 / Docker) |
| [example-question.md](example-question.md) | “이월결손금은 몇 년까지 공제?” 한 질문을 코드와 맞춰 보기 |
| [source/README.md](source/README.md) | `src/` · `tests/` 소스 파일·함수 상세 설명 |

## 한 줄 요약

국세청 신고안내 문서(법인세·부가가치세·연말정산)를 미리 넣어 두고,
사용자가 세무 질문을 하면 **문서에서 관련 부분을 찾아** 그 내용만 근거로 답하는 챗봇입니다.

검색 한 번으로 끝내지 않고, 답이 문서에 진짜 있는지 확인한 뒤
근거가 부족하면 검색어를 바꿔 **최대 2번까지 다시 찾습니다.**

## 읽는 순서

1. 프로그램이 뭔지 알고 싶다 → [overview.md](overview.md)
2. 안에서 어떻게 흘러가는지 보고 싶다 → [architecture.md](architecture.md)
3. 파일을 열고 싶다 → [files.md](files.md)
4. 내 PC에서 돌려보고 싶다 → [getting-started.md](getting-started.md)
5. 실제 질문 한 건이 코드를 어떻게 타는지 보고 싶다 → [example-question.md](example-question.md)
6. 소스 함수까지 읽고 싶다 → [source/README.md](source/README.md)

## 꼭 기억할 점

이 프로그램의 답변은 **학습·데모용**입니다.
실제 세무 판단이나 신고의 근거로 쓰지 마세요. 정확한 내용은 세무사 또는 [국세청](https://www.nts.go.kr) 공식 안내를 확인하세요.
