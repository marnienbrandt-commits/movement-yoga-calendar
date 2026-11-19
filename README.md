# Movement Colorado Yoga Calendar

A combined iCalendar feed for yoga classes at all six Colorado Movement locations:

- Baker
- Boulder
- Centennial
- Englewood
- Golden
- RiNo

The calendar is generated from Movement's public yoga schedule pages and refreshed daily by GitHub Actions. It includes class title/instructor text as published, local start/end times, gym location, and a link to the official schedule.

## Enable the public calendar URL

1. Open this repository's **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select branch **main** and folder **/(root)**, then save.
4. After GitHub Pages finishes publishing, the calendar URL will be:

   `https://marnienbrandt-commits.github.io/movement-yoga-calendar/calendar.ics`

5. On your iPhone, open **Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add Subscribed Calendar**, paste the URL, and save.

The repository and the published calendar are public. The feed contains only public class schedule information; do not add personal information or credentials here.

## How updates work

GitHub Actions runs every day at 14:15 UTC and can also be run manually from the **Actions** tab. The workflow reads each location's public yoga calendar in a browser, creates `calendar.ics`, and commits it only when the contents change.

The feed covers the current seven-day schedule displayed by Movement. Apple controls when subscribed calendars refresh on iPhone, so a new class or change may not appear immediately.

If Movement changes its website or calendar layout, the workflow may need an update. It deliberately fails rather than publishing a partial or empty feed if one of the six location pages cannot be read.
