# GitHub Token Rotation - Security Checklist

**Task:** subtask-1-1 - Rotate exposed GitHub token in GitHub settings
**Priority:** CRITICAL - Immediate execution required
**Date:** 2026-03-17

## ⚠️ CRITICAL SECURITY TASK

This checklist guides you through rotating an exposed GitHub personal access token to prevent unauthorized access to the repository.

---

## Step 1: Revoke Old Token

1. Navigate to GitHub Settings:
   - Go to https://github.com/settings/tokens
   - Or: Profile → Settings → Developer settings → Personal access tokens → Tokens (classic)

2. Identify the exposed token:
   - Look for tokens with names related to "ROAR", "CI", or "Protocol"
   - Check creation date and last used date
   - **Important:** Note the last 4 characters of the token for verification

3. Revoke the token:
   - Click on the token name
   - Click "Delete" or "Revoke" button
   - Confirm the deletion

**Status:** ⬜ COMPLETED (check when done)

---

## Step 2: Generate New Token

1. Create new personal access token:
   - Go to https://github.com/settings/tokens/new
   - **Token name:** `ROAR CI Token - Rotated 2026-03-17`
   - **Expiration:** 90 days (recommended for security)
   - **Description:** `Read-only token for ROAR Protocol CI workflows`

2. **CRITICAL:** Select MINIMAL permissions (read-only):
   - ✅ `repo:status` - Commit status
   - ✅ `repo_deployment` - Deployment status
   - ✅ `public_repo` - Access public repositories
   - ❌ **DO NOT** select: `repo` (full control), `admin`, `write`, or any other permissions

3. Generate the token:
   - Click "Generate token" at the bottom
   - **IMMEDIATELY COPY THE TOKEN** - You won't see it again!
   - Format: `ghp_` followed by 36 characters

4. Store temporarily in secure location:
   - Use a password manager (1Password, LastPass, Bitwarden)
   - Or write on paper to be destroyed after step 3

**Status:** ⬜ COMPLETED (check when done)
**Token starts with:** ghp_________________

---

## Step 3: Update GitHub Actions Secret

1. Navigate to repository secrets:
   - Go to the ROAR Protocol repository
   - Click "Settings" tab
   - Click "Secrets and variables" → "Actions"

2. Update the `GITHUB_TOKEN` secret:
   - Find `GITHUB_TOKEN` in the list
   - Click "Update" or "Delete" → "Add new secret"
   - **Name:** `GITHUB_TOKEN`
   - **Value:** Paste the new token from Step 2

3. Verify the secret is updated:
   - Confirm the secret appears in the list
   - Note the "Updated" timestamp

**Status:** ⬜ COMPLETED (check when done)

---

## Step 4: Verify Old Token Is Revoked

1. Return to GitHub Settings → Personal access tokens
2. Verify the old token is NO LONGER in the list
3. If it's still there, repeat Step 1

**Status:** ⬜ COMPLETED (check when done)

---

## Step 5: Test CI Workflows (Optional but Recommended)

1. Trigger a test workflow run:
   - Go to repository → Actions tab
   - Select a workflow (e.g., CI)
   - Click "Run workflow" → "Run workflow"

2. Verify the workflow succeeds:
   - Wait for workflow to complete
   - Check for any authentication errors
   - If errors occur, verify the secret was updated correctly

**Status:** ⬜ COMPLETED (check when done)

---

## Step 6: Secure Cleanup

1. Delete the new token from any temporary storage locations:
   - Close any text editors with the token
   - Clear clipboard: `echo "" | pbcopy` (macOS) or `echo "" | clip` (Windows)
   - Shred paper notes if used

2. Verify no tokens in password manager history (if applicable)

**Status:** ⬜ COMPLETED (check when done)

---

## Final Verification

Run these commands to verify no secrets remain in the codebase:

```bash
# Verify no GitHub tokens in files
git grep -E 'ghp_[a-zA-Z0-9]{36}'
# Expected: No matches

# Verify no token references in recent history
git log -S 'ghp_' --all --oneline | head -5
# Expected: No results (or only this commit)

# Verify no hardcoded secrets
git grep -iE 'password.*=|secret.*=|api.*key.*=' | grep -v '.example' | grep -v 'schema'
# Expected: No matches (excluding .example files)
```

**All verification commands passed:** ⬜ YES

---

## Security Best Practices

### ✅ DO:
- Use tokens with minimal required permissions
- Set expiration dates (90 days recommended)
- Rotate tokens regularly
- Store tokens in GitHub Secrets (never in code)
- Use different tokens for different purposes

### ❌ DON'T:
- Grant `repo` (full control) when read-only suffices
- Create tokens without expiration dates
- Store tokens in .env files committed to git
- Share tokens across multiple services
- Reuse revoked tokens

---

## Token Permissions Reference

For ROAR Protocol CI workflows, we only need:

| Permission | Scope | Why Needed |
|-----------|-------|------------|
| `repo:status` | Read commit status | CI workflow status checks |
| `repo_deployment` | Read deployment status | Deployment tracking |
| `public_repo` | Read public repos | Access to public ROAR Protocol repo |

**We explicitly DO NOT need:**
- `repo` (write access) - CI only reads
- `admin:repo_hook` - No webhook management
- `workflow` - GitHub Actions manages this automatically
- Any `write` or `delete` permissions

---

## Completion

Once all steps are completed:

1. Check all boxes above (⬜ → ✅)
2. Run the final verification commands
3. Inform the AI agent that manual rotation is complete
4. The agent will update the implementation plan status

**Date Completed:** _______________
**Completed By:** _______________
**New Token Expiration:** _______________

---

## Emergency Contacts

If you suspect the token is still exposed or being misused:

1. **Immediately revoke** both old and new tokens
2. Check GitHub Security Log: https://github.com/settings/security-log
3. Review repository audit log for unauthorized access
4. Generate a new token with a different name
5. Consider enabling 2FA if not already enabled

---

## Next Steps

After completing this checklist:

- [ ] Mark subtask-1-1 as "completed" in implementation_plan.json
- [ ] Commit this checklist as documentation
- [ ] Proceed to subtask-1-2: Scan codebase for exposed secrets (automated)
- [ ] Continue with subtask-1-3: Update CI workflows

**This is a blocking task** - All other production hardening work depends on securing access tokens first.
