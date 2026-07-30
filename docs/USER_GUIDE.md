# User Guide

This guide describes the interface that is actually available in the current
version as of 2026-07-30. For first-time server setup, see
[SETUP.md](SETUP.md).

## Access and Permissions

Open:

```text
http://127.0.0.1:8000/News.html
```

There are two types of users:

- A user with the `admin` role can generate, edit, save, and publish the
  newsletter, as well as manage versions.
- A user with the `user` role can view the published version and other versions
  available to them, without access to generation or editing tools.

The `admin / admin123` and `news / news123` accounts are for local development
only and may be different in the deployment environment. Do not use these
credentials in a shared or production environment.

## Generating a New Newsletter

1. Sign in with an administrator account.
2. On the start screen, select **Generate Newsletter**. The English label may
   appear briefly before the localized interface finishes loading.
3. Wait for the progress bar to complete. The system fetches sources, applies
   filtering and duplicate-memory checks, performs model selection and
   rewriting, saves the result, and then processes the course and movie
   content.
4. If generation fails, review the interface message and the run log before
   trying again. A retry may submit new model requests.

By default, the newsletter displays four news items. The editor can choose to
display six using the news-count menu. The system keeps alternative news items
in the background when they are available. The lower content section can
display either six courses or two movies, based on the saved data.

## Version Name

When saving a new version, the system uses the explicit title stored in the
metadata when one is available. Otherwise, it builds the name from the current
issue number and month in the newsletter settings, for example:

```text
AI Newsletter Issue 7 — July 2026
```

## Reviewing Content

On the newsletter page, the editor can:

- Select the displayed level: All, Beginner, Intermediate, or Advanced.
- Switch the lower section between courses and movies.
- Navigate between the alternatives saved for a card.
- Edit card fields using the edit button, then select **Save Changes**.
- Give the card-specific AI instructions using the `AI` tool.
- Delete an item and replace it with a suitable alternative when one is
  available.
- Select **Fetch New Item** when no saved alternative is available.
- Reorder cards by dragging them within the interface.
- Undo the most recent change using **Undo**.
- Edit the page title, footer text, issue number, and displayed month and year
  from **Settings**.

The level menu does not run a new search; it selects a saved view for the
current context. Likewise, navigating between alternatives does not
necessarily trigger a new fetch.

## Preview and Download

- **Preview** opens a clean preview of the current newsletter.
- **Download** generates a PDF from the currently displayed state and downloads
  it through the browser.
- Before downloading, select the required news count, level, and lower-section
  content type because the export uses the current view.

Email delivery is not available in the current version. The remaining elements
of the old interface were removed because they referred to a server route that
does not exist.

## Saving and Publishing a Version

Select **Save and Publish** after completing the review. The system then:

1. Saves the current display state in the workspace.
2. Creates a new version record in PostgreSQL, or updates the version when
   editing a restored version.
3. Uses the requested version title, or the current issue number and month.
4. Publishes the current state to the published-version file seen by viewing
   users.

If the same name already exists, the server rejects saving, PDF upload, or
renaming and displays: **A saved file with the same name already exists.
Choose a different name.** The system does not automatically add a suffix such
as `(2)` and does not overwrite the previous version.

## Managing Versions

Open **Manage Versions**, or go to:

```text
http://127.0.0.1:8000/versions.html
```

The page can sort versions from newest to oldest or oldest to newest. Depending
on the version type and the user's permissions, it supports:

- Previewing a saved version.
- Restoring a JSON version to the workspace and editing it.
- Downloading or exporting the version.
- Converting an editable version to PDF through the editing workflow.
- Hiding a version from viewing users or making it visible.
- Editing the version name or date.
- Deleting a version. This is an administrative action and cannot be undone
  from the interface.

An imported PDF version opens as a file and cannot be restored as editable JSON
cards.

## Actions That Are Not Automatic

- **Save and Publish** does not send an email.
- Changing the level filter does not fetch new news.
- The cost figures in the Excel workbook are planning estimates, not a live
  invoice.
- The version name is based on metadata or the current issue and month
  settings.

## Troubleshooting

- If generation and editing tools are missing, the account most likely does
  not have the `admin` role.
- If too few results are returned, check Gemini, Exa, SearXNG, and the internet
  connection, then review `backend/logs/ai_updates_run.jsonl`.
- If PDF generation fails outside Docker, run
  `python -m playwright install chromium`, then restart the server.
- For operational and backup details, see
  [MAINTENANCE.md](MAINTENANCE.md).
