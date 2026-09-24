#!/bin/bash
#
# Double-click this to push to GitHub and build in one go.
#
# It replaces doing three things by hand: pushing in GitHub Desktop,
# deleting the old app, and running the build. The delete was never
# needed - build.sh removes /Applications/Stem2AAF.app itself before
# moving the new one in.
#
# Push and build are deliberately independent here. A failed push is a
# credential problem, not a code problem, so it warns and builds anyway
# rather than leaving you with neither.

cd "$(dirname "$0")" || exit 1

echo "────────────────────────────────────────────"
echo "  Stem2AAF — push and build"
echo "────────────────────────────────────────────"
echo ""

# ── 1. Anything uncommitted? ────────────────────────────────────────────
# Deliberately does not auto-commit. A commit with a generated message is
# worth less than no commit at all - you can never find it again later.
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes in your working folder:"
    git status --short | sed 's/^/     /'
    echo ""
    echo "   These will be BUILT but not saved to GitHub."
    echo "   Commit them in GitHub Desktop first if you want them backed up."
    echo ""
fi

# ── 2. Push ─────────────────────────────────────────────────────────────
ahead=$(git rev-list --count origin/main..main 2>/dev/null || echo 0)
if [ "$ahead" -gt 0 ]; then
    echo "→ Pushing $ahead commit(s) to GitHub…"
    if git push 2>&1 | sed 's/^/   /'; then
        echo "   ✓ Pushed"
    else
        echo ""
        echo "   ⚠️  Push failed — carrying on with the build."
        echo "      Usually means credentials. Open GitHub Desktop and"
        echo "      click Push origin, or just try this again later."
    fi
else
    echo "→ Nothing to push, GitHub is up to date."
fi
echo ""

# ── 3. Build ────────────────────────────────────────────────────────────
echo "→ Building… (a minute or two; the app is replaced in /Applications)"
echo ""
bash build.sh
status=$?

echo ""
if [ $status -eq 0 ]; then
    echo "────────────────────────────────────────────"
    echo "  Done. Open Stem2AAF from /Applications."
    echo "────────────────────────────────────────────"
else
    echo "────────────────────────────────────────────"
    echo "  Build failed — see the messages above,"
    echo "  or ~/Desktop/Stem2AAF_build_log.txt"
    echo "────────────────────────────────────────────"
fi

echo ""
echo "Press any key to close…"
read -n 1
