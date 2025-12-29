#!/bin/bash
# Creates a new git worktree with venv and .env symlinked from main worktree
#
# Usage: ./scripts/create-worktree.sh <branch-name> [path]
# Example: ./scripts/create-worktree.sh feature/new-feature
#          ./scripts/create-worktree.sh feature/new-feature /Users/ankesh/code/collab/my-feature

set -e

MAIN_WORKTREE="/Users/ankesh/code/collab/vm-api"
BRANCH_NAME="$1"
WORKTREE_PATH="${2:-/Users/ankesh/code/collab/$(echo $BRANCH_NAME | sed 's/.*\///')}"

if [ -z "$BRANCH_NAME" ]; then
    echo "Usage: $0 <branch-name> [path]"
    echo "Example: $0 ankesh/vib-123-new-feature"
    exit 1
fi

echo "Creating worktree for branch: $BRANCH_NAME"
echo "Path: $WORKTREE_PATH"

# Create the worktree
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>/dev/null || \
git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"

# Symlink venv, .env, and .claude
ln -s "$MAIN_WORKTREE/venv" "$WORKTREE_PATH/venv"
ln -s "$MAIN_WORKTREE/.env" "$WORKTREE_PATH/.env"
ln -s "$MAIN_WORKTREE/.claude" "$WORKTREE_PATH/.claude"

echo ""
echo "✅ Worktree created successfully!"
echo "   Path: $WORKTREE_PATH"
echo "   venv: symlinked"
echo "   .env: symlinked"
echo "   .claude: symlinked"
echo ""
echo "To start working:"
echo "   cd $WORKTREE_PATH"
