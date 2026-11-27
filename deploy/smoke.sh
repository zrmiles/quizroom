#!/usr/bin/env bash
# Проверка поднятого стека (docker compose up): страница, API через nginx, заголовки, вход ведущего.
# Использование: deploy/smoke.sh [адрес], по умолчанию http://localhost:8080
set -euo pipefail

BASE="${1:-http://localhost:8080}"
fail() { echo "FAIL $*" >&2; exit 1; }
ok() { echo "OK   $*"; }

for _ in $(seq 1 60); do
  curl -fsS "$BASE/api/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "$BASE/api/health" | grep -q '"ok"' || fail "API не отвечает через nginx"
ok "API и база отвечают"

headers=$(curl -fsSI "$BASE/")
grep -qi '^content-security-policy:.*default-src' <<<"$headers" || fail "нет Content-Security-Policy"
grep -qi '^x-frame-options: DENY' <<<"$headers" || fail "нет X-Frame-Options"
grep -qi '^server: nginx$' <<<"$headers" && fail "nginx раскрывает версию"
ok "заголовки безопасности на странице"

curl -fsS "$BASE/quizzes/123/edit" | grep -q '<div id="root">' || fail "SPA не отдаёт index.html на внутренних адресах"
ok "внутренние адреса SPA открываются"

email="smoke-$(date +%s)-$RANDOM@example.com"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"email\":\"$email\",\"username\":\"Smoke\",\"password\":\"smoke-password-1\"}" "$BASE/api/auth/register")
[ "$code" = 201 ] || fail "регистрация вернула $code"
token=$(curl -fsS -H 'Content-Type: application/json' \
  -d "{\"email\":\"$email\",\"password\":\"smoke-password-1\"}" "$BASE/api/auth/login" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
quiz=$(curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d '{"title":"Smoke","questions":[{"type":"single","text":"?","options":[{"text":"да","is_correct":true},{"text":"нет"}]}]}' "$BASE/api/quizzes" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
pin=$(curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d "{\"quiz_id\":$quiz}" "$BASE/api/sessions" | python3 -c 'import json,sys;print(json.load(sys.stdin)["pin"])')
curl -fsS "$BASE/api/sessions/$pin" | grep -q '"lobby"' || fail "комната не открылась"
ok "регистрация, вход, викторина и комната через nginx"

echo "Все проверки пройдены"
