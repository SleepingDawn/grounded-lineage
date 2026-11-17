#!/bin/zsh
set -eu
umask 077
cd "$(dirname "$0")/.."

printf '\n서울대 학외접속 로그인\n'
printf '열리는 브라우저의 주소를 확인한 뒤 직접 로그인하세요.\n'
printf '학교 비밀번호를 채팅이나 설정 파일에 입력하지 마세요.\n'
printf '원문 페이지가 열리면 이 창으로 돌아와 Enter를 누르세요.\n\n'

if .venv/bin/scholarly-access-agent open-url \
    'https://www.nature.com/articles/s43588-023-00561-9' \
    --wait-for-login --headless false --timeout-ms 60000; then
    printf '\n완료: 개인 전용 위치에 로그인 세션을 저장했습니다.\n'
else
    printf '\n로그인이 완료되지 않았습니다. 창을 닫고 다시 실행할 수 있습니다.\n'
fi
printf '\nEnter를 누르면 이 창을 닫습니다.\n'
read -r
