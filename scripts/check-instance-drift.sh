#!/usr/bin/env bash

# FastAPI Template Instance Drift Checker
# Compare instance template version vs current template HEAD

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'  # No Color

# ============================================================================
# Functions
# ============================================================================

_green() {
	echo -e "${GREEN}$*${NC}"
}

_yellow() {
	echo -e "${YELLOW}$*${NC}"
}

_blue() {
	echo -e "${BLUE}$*${NC}"
}

_error() {
	echo -e "${RED}✗${NC} $*" >&2
	return 1
}

main() {
	# Validate arguments
	if [[ $# -ne 1 ]]; then
		_error "Usage: $0 <instance-path>"
		echo "Example: $0 $HOME/workspace/meta-work/fastapi-template-test-instance"
		return 1
	fi

	local instance_dir="$1"
	local template_dir
	template_dir="$(cd "$(dirname "$0")/.." && pwd)"

	# Validate instance exists
	if [[ ! -d "$instance_dir" ]]; then
		_error "Instance directory not found: $instance_dir"
		return 1
	fi

	# Validate .copier-answers.yml exists
	if [[ ! -f "$instance_dir/.copier-answers.yml" ]]; then
		_error "Not a copier instance: $instance_dir/.copier-answers.yml not found"
		return 1
	fi

	# Get current template commit
	local template_commit
	template_commit=$(git -C "$template_dir" rev-parse HEAD)

	# Get instance template commit from .copier-answers.yml
	local instance_commit
	instance_commit=$(grep "_commit:" "$instance_dir/.copier-answers.yml" | awk '{print $2}')

	if [[ -z "$instance_commit" ]]; then
		_error "Could not find _commit in $instance_dir/.copier-answers.yml"
		return 1
	fi

	# Compare commits
	if [[ "$template_commit" == "$instance_commit" ]]; then
		_green "✅ Up-to-date"
		echo "Instance: $instance_dir"
		echo "Template commit: $template_commit"
		return 0
	fi

	# Instance is behind - show details
	_yellow "⚠️  Instance is behind template"
	echo ""
	echo "Instance location: $instance_dir"
	echo "Instance template commit: $instance_commit"
	echo "Template HEAD: $template_commit"
	echo ""

	# Count commits behind
	local commits_behind
	commits_behind=$(git -C "$template_dir" rev-list --count "$instance_commit".."$template_commit")
	_yellow "Commits behind: $commits_behind"
	echo ""

	# Show recent changes
	_blue "Recent template changes:"
	git -C "$template_dir" log --oneline --no-decorate "$instance_commit".."$template_commit" | head -20
	echo ""

	# Show how to update
	_blue "To update this instance:"
	echo "  cd \"$instance_dir\""
	echo "  copier update --trust"
	echo "  pytest  # Verify after update"
	echo ""

	return 0
}

# Run main if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
	main "$@"
fi
