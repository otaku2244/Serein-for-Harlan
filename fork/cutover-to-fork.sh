#!/usr/bin/env bash
# Serein · 一次性把安装目录的更新来源从上游切到自建 fork
#
# 默认只体检，不改任何东西。看清体检报告后加 --apply 才真正执行。
#
#   bash cutover-to-fork.sh                    # 体检（只读）
#   bash cutover-to-fork.sh --apply            # 执行（更新器默认先备份数据）
#   bash cutover-to-fork.sh --apply --skip-data-backup
#   bash cutover-to-fork.sh --apply --force    # 仅当体检报“源码漂移”时使用，见 UPGRADE.md
#
# 幂等：重复执行只会在第 2、3 步发现“已经切过了”并跳过。
#
set -euo pipefail

FORK_OWNER="otaku2244"
FORK_REPO="Serein-for-Harlan"
FORK_BRANCH="main"
FORK_SLUG="${FORK_OWNER}/${FORK_REPO}"
FORK_REMOTE="https://github.com/${FORK_SLUG}.git"
ROOT="${SEREIN_ROOT:-/root/Serein}"
UPDATER_REL="scripts/upstream_update.py"
RAW_UPDATER="https://raw.githubusercontent.com/${FORK_SLUG}/${FORK_BRANCH}/${UPDATER_REL}"

APPLY=0
DATA_BACKUP=1
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --apply)             APPLY=1 ;;
    --skip-data-backup)  DATA_BACKUP=0 ;;
    --force)             FORCE=1 ;;
    -h|--help)           sed -n '2,14p' "$0"; exit 0 ;;
    *) printf '未知参数：%s\n' "$arg" >&2; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
STATE="${ROOT}/deploy/update-state.json"
TMP=""

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   [OK]   %s\n' "$*"; }
warn() { printf '   [注意] %s\n' "$*"; }
die()  { printf '\n   [中止] %s\n' "$*" >&2; exit 1; }
plan() { if [ "$APPLY" = 1 ]; then printf '   [执行] %s\n' "$*"; else printf '   [将执行] %s\n' "$*"; fi; }

cleanup() { if [ -n "$TMP" ] && [ -f "$TMP" ]; then rm -f "$TMP" || true; fi; }
trap cleanup EXIT

if [ "$APPLY" != 1 ]; then
  printf '\n\033[1m体检模式\033[0m：只读取和校验，不会改动任何文件。\n'
  printf '确认无误后加 --apply 执行。\n'
fi

# ─────────────────────────────────────────────── 0. 环境
say "0/6 环境检查"
[ "$(id -u)" = "0" ] || die "请用 root 运行（需要读写 ${ROOT} 和操作 Docker）。"
[ -d "$ROOT" ] || die "找不到安装目录：$ROOT（可用 SEREIN_ROOT=... 指定）"
[ -f "$ROOT/deploy/config.toml" ] || die "$ROOT 不是已部署的实例（缺少 deploy/config.toml）。"
[ -f "$ROOT/release-files.json" ] || die "$ROOT 缺少 release-files.json。"
[ -f "$ROOT/$UPDATER_REL" ] || die "$ROOT 缺少 $UPDATER_REL。"
command -v git >/dev/null 2>&1 || die "缺少 git，更新器需要它。"
command -v python3 >/dev/null 2>&1 || die "缺少 python3，管理菜单需要它。"
FETCH=""
if   command -v curl >/dev/null 2>&1; then FETCH="curl"
elif command -v wget >/dev/null 2>&1; then FETCH="wget"
else die "缺少 curl 或 wget，无法取回新更新器。"
fi
ok "安装目录 $ROOT"
ok "取回工具 $FETCH"

# ─────────────────────────────────────────────── 1. fork 可达
say "1/6 确认 fork 已推送且可读"
FORK_HEAD="$(git ls-remote "$FORK_REMOTE" "refs/heads/${FORK_BRANCH}" 2>/dev/null | awk '{print $1}' | head -n 1)"
[ -n "${FORK_HEAD:-}" ] || die "读不到 ${FORK_REMOTE} 的 ${FORK_BRANCH} 分支。
        请先在本地把仓库推上去，例如：
          cd <本地 Serein-fork>
          git remote add origin ${FORK_REMOTE}
          git push -u origin ${FORK_BRANCH}"
ok "fork ${FORK_BRANCH} @ ${FORK_HEAD:0:12}"

# ─────────────────────────────────────────────── 2. 源码台账
say "2/6 核对安装源码与上次更新记录"
VERDICT="$(python3 - "$ROOT" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location('installed_updater', root / 'scripts' / 'upstream_update.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state_path = root / 'deploy' / 'update-state.json'
if not state_path.is_file():
    print('NOSTATE'); raise SystemExit(0)
state = json.loads(state_path.read_text())
managed = state.get('source_hashes')
if not managed:
    print('NOHASHES'); raise SystemExit(0)
try:
    actual = module.source_hashes(root)
except Exception as exc:
    print('UNREADABLE'); print(type(exc).__name__ + ': ' + str(exc)); raise SystemExit(0)
if actual == managed:
    print('CLEAN')
    print('commit=' + str(state.get('commit', '')))
    print('phase=' + str(state.get('phase', '')))
    print('files=' + str(len(managed)))
    raise SystemExit(0)
drift = sorted(k for k in set(managed) | set(actual) if managed.get(k) != actual.get(k))
print('DIRTY')
for name in drift[:20]:
    print('   ' + name)
if len(drift) > 20:
    print('   ... 其余 %d 个' % (len(drift) - 20))
print('total=' + str(len(drift)))
PY
)"
VERDICT_CODE="$(printf '%s\n' "$VERDICT" | head -n 1)"
case "$VERDICT_CODE" in
  CLEAN)
    ok "源码与更新记录完全一致，更新器的第一道校验会放行。"
    printf '%s\n' "$VERDICT" | sed -n '2,4p' | sed 's/^/   /'
    ;;
  NOSTATE|NOHASHES)
    warn "没有可用的更新台账（$VERDICT_CODE）。"
    warn "这意味着更新器的第二道校验会退到 .git 检查，必须先把 .git 摘掉。"
    if [ "$FORCE" != 1 ]; then
      die "为避免误覆盖，请加 --force 明确表示接受这一情况（详见 UPGRADE.md）。"
    fi
    ;;
  UNREADABLE)
    printf '%s\n' "$VERDICT" | sed -n '2p' | sed 's/^/   /'
    die "读不了当前源码清单，无法判断漂移。"
    ;;
  DIRTY)
    warn "以下文件与上次更新记录不一致："
    printf '%s\n' "$VERDICT" | sed -n '2,$p' | sed 's/^/   /'
    if [ "$FORCE" != 1 ]; then
      die "更新器的第一道校验会因此拒绝执行。请先弄清这些改动来自哪里；
        若确认它们可以被 fork 源码覆盖，再加 --force 执行。"
    fi
    warn "--force：将把 update-state.json 移开，并摘掉 .git，让更新器跳过全部三道校验，"
    warn "        然后用 fork 源码整体覆盖上述文件。这些改动不会保留。"
    ;;
  *)
    die "体检脚本返回了看不懂的结果：$VERDICT_CODE"
    ;;
esac

# ─────────────────────────────────────────────── 3. 取回新更新器
say "3/6 取回指向 fork 的更新器"
TMP="$(mktemp)"
if [ "$FETCH" = "curl" ]; then
  curl -fsSL --max-time 60 "$RAW_UPDATER" -o "$TMP" || die "下载失败：$RAW_UPDATER"
else
  wget -q -T 60 -O "$TMP" "$RAW_UPDATER" || die "下载失败：$RAW_UPDATER"
fi
grep -q "REPOSITORY = '${FORK_SLUG}'" "$TMP" \
  || die "下载到的更新器指向的不是 ${FORK_SLUG}，已放弃替换。"
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$TMP" \
  || die "下载到的更新器语法不通过，已放弃替换。"
# Windows 版 sha256sum 会在文件名含反斜杠时给整行加转义前缀，先去掉再取前 16 位。
ok "已取回并校验：$(sha256sum "$TMP" | tr -d '\\' | cut -c1-16)…  指向 ${FORK_SLUG}"

# ─────────────────────────────────────────────── 4. 落地
say "4/6 落地：备份台账 → 摘掉上游 .git → 换更新器"
if [ -f "$STATE" ]; then
  plan "备份 $STATE → ${STATE}.before-fork-${STAMP}"
  if [ "$APPLY" = 1 ]; then cp -a "$STATE" "${STATE}.before-fork-${STAMP}"; fi
else
  ok "没有 update-state.json 可备份（本次是首次接入更新）。"
fi

if [ -d "$ROOT/.git" ]; then
  plan "改名 $ROOT/.git → $ROOT/.git.upstream-${STAMP}（只改名，随时可改回）"
  if [ "$APPLY" = 1 ]; then mv "$ROOT/.git" "$ROOT/.git.upstream-${STAMP}"; fi
else
  ok "没有 .git 检出，跳过（说明之前已经切过，或本来就是解压安装）。"
fi

plan "备份并替换 $ROOT/$UPDATER_REL"
if [ "$APPLY" = 1 ]; then
  cp -a "$ROOT/$UPDATER_REL" "$ROOT/${UPDATER_REL}.before-fork-${STAMP}"
  install -m 0644 "$TMP" "$ROOT/$UPDATER_REL"
fi

if [ "$FORCE" = 1 ] && [ "$VERDICT_CODE" != "CLEAN" ] && [ -f "$STATE" ]; then
  plan "（--force）把 $STATE 改名移开，让更新器跳过全部三道校验"
  if [ "$APPLY" = 1 ]; then
    mv "$STATE" "${STATE}.drifted-${STAMP}"
  fi
fi

# ─────────────────────────────────────────────── 5. 跑更新
say "5/6 用 fork 源码覆盖并重建（中间会停服，构建较慢）"
if [ "$DATA_BACKUP" = 1 ]; then
  printf '   更新器选项：1 = 先备份数据再更新（上游默认）\n'
else
  printf '   更新器选项：0 = 跳过数据备份直接更新\n'
fi
printf '   manage.py 会连续吃到两个选项：菜单 1、备份选择 %s\n' "$DATA_BACKUP"
plan "printf '1\\n%s\\n' | python3 $ROOT/scripts/manage.py"
if [ "$APPLY" = 1 ]; then
  cd "$ROOT"
  printf '1\n%s\n' "$DATA_BACKUP" | python3 "$ROOT/scripts/manage.py" || true
  cd - >/dev/null
  warn "管理菜单的退出码不可信（更新失败它也会以 0 退出），结果看第 6 步的独立校验。"
fi

# ─────────────────────────────────────────────── 6. 独立校验
say "6/6 独立校验切换结果"
if [ "$APPLY" != 1 ]; then
  printf '   体检结束。上面的 [将执行] 就是 --apply 时会做的事。\n'
  printf '   回滚方法见 fork/UPGRADE.md。\n\n'
  exit 0
fi

python3 - "$ROOT" "$FORK_HEAD" "$FORK_SLUG" <<'PY'
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
expected_commit, expected_slug = sys.argv[2], sys.argv[3]
lines = []
bad = 0

def check(label, ok, detail=''):
    global bad
    lines.append(('  [OK]   ' if ok else '  [失败] ') + label + (('  ' + detail) if detail and not ok else ''))
    if not ok:
        bad += 1

state_path = root / 'deploy' / 'update-state.json'
state = json.loads(state_path.read_text()) if state_path.is_file() else {}
check('update-state.json 存在', state_path.is_file())
check('记录指向 fork', state.get('repository') == expected_slug, str(state.get('repository')))
check('提交 == fork 的 main', state.get('commit') == expected_commit,
      '%s vs %s' % (str(state.get('commit'))[:12], expected_commit[:12]))
check('阶段为 complete', state.get('phase') == 'complete', str(state.get('phase')))

new_file = root / 'src' / 'serein' / 'chat_resume_auto.py'
check('新模块已落地', new_file.is_file())
if new_file.is_file():
    compiled = subprocess.run([sys.executable, '-m', 'py_compile', str(new_file)],
                              capture_output=True)
    check('新模块语法通过', compiled.returncode == 0, compiled.stderr.decode('utf-8', 'replace')[:160])

manifest = json.loads((root / 'release-files.json').read_text(encoding='utf-8'))
check('发布清单含新模块', 'src/serein/chat_resume_auto.py' in manifest)
check('发布清单含新开关界面', 'web/src/components/FeatureSettings.jsx' in manifest)

if state.get('source_hashes'):
    spec = importlib.util.spec_from_file_location('installed_updater', root / 'scripts' / 'upstream_update.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check('台账与磁盘完全一致（se → 1 以后可直接复用）',
          module.source_hashes(root) == state['source_hashes'])
    check('更新器已指向 fork', module.REPOSITORY == expected_slug, module.REPOSITORY)
else:
    check('台账有 source_hashes', False, '缺失')

try:
    ps = subprocess.run(['docker', 'ps', '--format', '{{.Names}}\t{{.Status}}'],
                        capture_output=True, text=True)
    running = ps.stdout if ps.returncode == 0 else ''
except OSError as exc:
    running = ''
    lines.append('  [注意] 没能调用 docker（%s），容器状态请自行执行 docker ps 确认' % type(exc).__name__)
for needle in ('-memory-1', '-gateway-1'):
    row = [l for l in running.splitlines() if needle in l]
    check('容器 %s 在跑' % needle, bool(row) and 'Up' in row[0], row[0] if row else '没有这个容器')

print()
print('\n'.join(lines))
print()
if bad:
    print('  %d 项没通过。先别开开关，把上面的失败项贴出来排查；回滚方法见 fork/UPGRADE.md。' % bad)
    raise SystemExit(1)
print('  全部通过。接下来在设置页打开「开窗续接」和「新窗自动续接」，然后开一个新窗口发第一条消息验证。')
PY

printf '\n'
printf '  本次留下的现场（都不影响运行，确认稳定后可以删）：\n'
printf '    %s\n' "${STATE}.before-fork-${STAMP}"
if [ -d "$ROOT/.git.upstream-${STAMP}" ]; then printf '    %s\n' "$ROOT/.git.upstream-${STAMP}"; fi
printf '    %s\n' "$ROOT/${UPDATER_REL}.before-fork-${STAMP}"
printf '  源码备份 zip 在 %s/deploy/backups/（更新器自动留的）\n\n' "$ROOT"
