import discord
from discord import app_commands
from discord.ext import commands
import httpx
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os

COLOR_BLUE = 0x3498db

class CommentPaginator(discord.ui.View):
    def __init__(self, comments, page_size=5):
        super().__init__(timeout=300)
        self.comments = comments
        self.page_size = page_size
        self.page = 0

        self.prev_button = discord.ui.Button(label="⏪ Prev", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next ⏩", style=discord.ButtonStyle.secondary)

        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

        self.update_button_states()

    def update_button_states(self):
        total_pages = (len(self.comments) + self.page_size - 1) // self.page_size
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= total_pages - 1

    def format_embed(self):
        embed = discord.Embed(
            title=f"💬 Comments — Page {self.page + 1}",
            color=COLOR_BLUE
        )
        start = self.page * self.page_size
        end = min(start + self.page_size, len(self.comments))

        for comment in self.comments[start:end]:
            user = comment["user"]["login"]
            created_at = comment["created_at"][:10]
            body = comment["body"][:500] + ("..." if len(comment["body"]) > 500 else "")
            embed.add_field(name=f"{user} — {created_at}", value=body or "*No content*", inline=False)

        embed.set_footer(text=f"Showing {start + 1}-{end} of {len(self.comments)}")
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_button_states()
            await interaction.response.edit_message(embed=self.format_embed(), view=self)
        else:
            await interaction.response.defer()

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.comments) + self.page_size - 1) // self.page_size
        if self.page < total_pages - 1:
            self.page += 1
            self.update_button_states()
            await interaction.response.edit_message(embed=self.format_embed(), view=self)
        else:
            await interaction.response.defer()


class NewIssueModal(discord.ui.Modal, title="Create a New GitHub Issue"):
    title_input = discord.ui.TextInput(label="Title", placeholder="Issue title", max_length=256)
    body_input = discord.ui.TextInput(label="Body", style=discord.TextStyle.paragraph, required=False, placeholder="Describe the issue")

    def __init__(self, repo: str, token: str):
        super().__init__()
        self.repo = repo
        self.token = token

    async def on_submit(self, interaction: discord.Interaction):
        owner, repo_name = self.repo.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        json_data = {
            "title": self.title_input.value,
            "body": self.body_input.value
        }
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, json=json_data)
            data = res.json()

        if res.status_code == 201:
            await interaction.response.send_message(f"✅ Issue created: [{data['title']}]({data['html_url']})", ephemeral=True)
        else:
            message = data.get("message", "Unknown error.")
            await interaction.response.send_message(f"❌ Failed to create issue: {message}", ephemeral=True)

class Issue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
        self.users_collection = self.mongo_client.gitbot.users

    issue_group = app_commands.Group(name="issue", description="Commands for GitHub issues")

    async def _fetch_and_display_issue_list(self, interaction: discord.Interaction, owner: str, repo_name: str, state: str):
        headers = {"Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues?state={state}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                await interaction.followup.send(f"Could not fetch {state} issues for `{owner}/{repo_name}`. Status: {r.status_code}")
                return
            issues_data = r.json()

            if not issues_data:
                await interaction.followup.send(f"No {state} issues found for `{owner}/{repo_name}`.")
                return

            embed = discord.Embed(
                title=f"{state.capitalize()} Issues for {owner}/{repo_name}",
                color=COLOR_BLUE
            )
            for issue_item in issues_data:
                title = issue_item["title"]
                number = issue_item["number"]
                html_url = issue_item["html_url"]
                user = issue_item["user"]["login"]
                embed.add_field(name=f"#{number}: {title}", value=f"Opened by {user} ([Link]({html_url}))", inline=False)

            await interaction.followup.send(embed=embed)

    async def _fetch_and_display_single_issue(self, interaction: discord.Interaction, owner: str, repo_name: str, issue_id: int):
        headers = {"Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_id}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                await interaction.followup.send(f"Could not find issue `#{issue_id}` in `{owner}/{repo_name}`. Status: {r.status_code}")
                return
            issue_data = r.json()

            title = issue_data["title"]
            number = issue_data["number"]
            user = issue_data["user"]["login"]
            state = issue_data["state"]
            html_url = issue_data["html_url"]
            created_at = datetime.strptime(issue_data["created_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S UTC")
            body = issue_data["body"] if issue_data["body"] else "No description provided."
            comments = issue_data["comments"]

            embed = discord.Embed(
                title=f"Issue #{number}: {title}",
                url=html_url,
                description=body,
                color=COLOR_BLUE
            )
            embed.add_field(name="Repository", value=f"{owner}/{repo_name}", inline=True)
            embed.add_field(name="Status", value=state.capitalize(), inline=True)
            embed.add_field(name="Opened By", value=user, inline=True)
            embed.add_field(name="Created At", value=created_at, inline=False)
            embed.add_field(name="Comments", value=str(comments), inline=True)

            await interaction.followup.send(embed=embed)

    @issue_group.command(name="open", description="Get information on open GitHub issues")
    @app_commands.describe(
        repo="Repository in the form of owner/repo (e.g. myferr/x3)",
        issue_id="Optional: Issue ID (e.g. 1). If not provided, lists all open issues."
    )
    async def issue_open(self, interaction: discord.Interaction, repo: str, issue_id: int = None):
        await interaction.response.defer()
        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            await interaction.followup.send("Invalid repository format. Please use `owner/repo` (e.g., `myferr/x3`).")
            return

        if issue_id is None:
            await self._fetch_and_display_issue_list(interaction, owner, repo_name, "open")
        else:
            await self._fetch_and_display_single_issue(interaction, owner, repo_name, issue_id)

    @issue_group.command(name="closed", description="Get information on closed GitHub issues")
    @app_commands.describe(
        repo="Repository in the form of owner/repo (e.g. myferr/x3)",
        issue_id="Optional: Issue ID (e.g. 1). If not provided, lists all closed issues."
    )
    async def issue_closed(self, interaction: discord.Interaction, repo: str, issue_id: int = None):
        await interaction.response.defer()
        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            await interaction.followup.send("Invalid repository format. Please use `owner/repo` (e.g., `myferr/x3`).")
            return

        if issue_id is None:
            await self._fetch_and_display_issue_list(interaction, owner, repo_name, "closed")
        else:
            await self._fetch_and_display_single_issue(interaction, owner, repo_name, issue_id)

    @issue_group.command(name="close", description="Close a GitHub issue (requires authentication)")
    @app_commands.describe(
        repo="Repository in the form of owner/repo (e.g. myferr/x3)",
        issue_id="Issue ID to close"
    )
    async def issue_close(self, interaction: discord.Interaction, repo: str, issue_id: int):
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        user = await self.users_collection.find_one({"discord_id": discord_id})
        if not user:
            await interaction.followup.send("❌ You must link your GitHub account using `/auth` before closing issues.", ephemeral=True)
            return

        from token_handler import TokenHandler
        token_handler = TokenHandler()
        token = token_handler.decrypt(user.get("token")) if user and user.get("token") else None
        if not token:
            await interaction.followup.send("❌ Your GitHub token is missing. Please re-authenticate with `/auth`.", ephemeral=True)
            return

        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            await interaction.followup.send("Invalid repository format. Use `owner/repo`.", ephemeral=True)
            return

        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_id}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        json_data = {
            "state": "closed"
        }
        async with httpx.AsyncClient() as client:
            res = await client.patch(url, headers=headers, json=json_data)
            data = res.json()

        if res.status_code == 200 and data.get("state") == "closed":
            await interaction.followup.send(f"✅ Issue #{issue_id} has been closed.", ephemeral=True)
        else:
            message = data.get("message", "Unknown error.")
            await interaction.followup.send(f"❌ Failed to close issue #{issue_id}: {message}", ephemeral=True)

    @issue_group.command(name="new", description="Open a modal to create a new GitHub issue (requires authentication)")
    @app_commands.describe(
        repo="Repository in the form of owner/repo (e.g. myferr/x3)"
    )
    async def issue_new(self, interaction: discord.Interaction, repo: str):
        discord_id = str(interaction.user.id)
        user = await self.users_collection.find_one({"discord_id": discord_id})
        if not user:
            await interaction.response.send_message("❌ You must link your GitHub account using `/auth` before creating issues.", ephemeral=True)
            return

        token = user.get("token")
        if not token:
            await interaction.response.send_message("❌ Your GitHub token is missing. Please re-authenticate with `/auth`.", ephemeral=True)
            return

        modal = NewIssueModal(repo, token)
        await interaction.response.send_modal(modal)

    @issue_group.command(name="comments", description="List comments on a GitHub issue")
    @app_commands.describe(repo="owner/repo", issue_id="Issue number")
    async def issue_comments(self, interaction: discord.Interaction, repo: str, issue_id: int):
        await interaction.response.defer()
        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            await interaction.followup.send("Invalid repository format. Use `owner/repo`.")
            return

        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_id}/comments"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers={"Accept": "application/vnd.github.v3+json"})
            if r.status_code != 200:
                await interaction.followup.send(f"❌ Failed to fetch comments. ({r.status_code})")
                return

            comments = r.json()
            if not comments:
                await interaction.followup.send("💬 No comments found.")
                return

            paginator = CommentPaginator(comments)
            await interaction.followup.send(embed=paginator.format_embed(), view=paginator)


    @issue_group.command(name="comment", description="Post a comment on a GitHub issue (requires authentication)")
    @app_commands.describe(repo="owner/repo", issue_id="Issue number", comment="Your comment text")
    async def issue_comment(self, interaction: discord.Interaction, repo: str, issue_id: int, comment: str):
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        user = await self.users_collection.find_one({"discord_id": discord_id})
        if not user or not user.get("token"):
            await interaction.followup.send("❌ You must link your GitHub account using `/auth`.", ephemeral=True)
            return
        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            await interaction.followup.send("Invalid repository format. Use `owner/repo`.", ephemeral=True)
            return

        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_id}/comments"
        headers = {
            "Authorization": f"token {user['token']}",
            "Accept": "application/vnd.github.v3+json"
        }

        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, json={"body": comment})
            if r.status_code == 201:
                await interaction.followup.send("✅ Comment posted successfully.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed to post comment. ({r.status_code})", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Issue(bot))

