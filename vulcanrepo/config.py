NAMESPACED_STATIC_DIRS = {
    "repo": "vulcanrepo:base/static"
}

REPO_TOOL_SPEC = {
    "git": {
        "app_path": "vulcanrepo.git.git_main:ForgeGitApp",
        "installable": True
    },
    "svn": {
        "app_path": "vulcanrepo.svn.svn_main:ForgeSVNApp",
        "installable": True
    }
}