# ECU Hockey Calendar Sync Guide

Never miss an East Carolina University Men's Ice Hockey matchup! This guide walks you through subscribing to the live, auto-updating ECU Hockey schedule in your preferred calendar application.

## 1. Why Subscribe Instead of Importing?

When you add a sports schedule to your calendar, you have two choices:

- **Subscribe to the live feed (Recommended)**: Your calendar application maintains an active connection to the schedule service. When games are announced, rescheduled, postponed, or times change, your calendar automatically updates in the background. You set it up once and stay up to date all season long.
- **One-time file import**: A downloaded `.ics` file is a static snapshot frozen in time. If puck drop is delayed, a venue changes, or playoff dates are scheduled, an imported calendar will not reflect those updates.

Subscribing gives you an automated, hands-off schedule that updates itself as games move.

## 2. Subscription URLs

Choose the URL that matches your device and calendar client:

| Calendar Client                           | Method                      | Subscription URL                                                                                 |
| :---------------------------------------- | :-------------------------- | :----------------------------------------------------------------------------------------------- |
| **Apple Calendar (iOS / iPadOS / macOS)** | One-Click Instant Subscribe | [Subscribe to ECU Hockey Schedule](https://ecu-hockey-api.onrender.com/calendar.ics?webcal=true) |
| **Apple Calendar (macOS manual)**         | Webcal Feed                 | `webcal://ecu-hockey-api.onrender.com/calendar.ics`                                              |
| **Google Calendar, Outlook, and others**  | Add by URL (HTTPS)          | `https://ecu-hockey-api.onrender.com/calendar.ics`                                               |

> [!TIP]
> On iPhone, iPad, and Mac, clicking [Subscribe to ECU Hockey Schedule](https://ecu-hockey-api.onrender.com/calendar.ics?webcal=true) will prompt your device to open Apple Calendar and subscribe immediately.

## 3. Step-by-Step Setup by Application

### 3.1. Apple Calendar (iPhone & iPad / iOS)

You can subscribe to the calendar on your mobile Apple device using either the instant one-click method or the manual settings menu.

#### 3.1.1. Method A: One-Click Instant Subscription (Easiest)

1. Open this page in **Safari** on your iPhone or iPad.
2. Tap the one-click link: [Subscribe to ECU Hockey Schedule](https://ecu-hockey-api.onrender.com/calendar.ics?webcal=true).
3. A system prompt will appear asking: *"Subscribe to calendar 'ECU Men's Ice Hockey Schedule'?"*.
4. Tap **Subscribe**.
5. Choose your preferences:
   - **Account**: Select **iCloud** if you want the schedule to automatically sync across all your devices (Mac, iPad, Apple Watch).
   - **Auto-Refresh**: Set to **Every hour** or **Every day**.
6. Tap **Add** (or **Done**).

#### 3.1.2. Method B: Manual Settings Subscription

1. Open the **Settings** app on your iPhone or iPad.

2. Scroll down and tap **Apps** > **Calendar** (or tap **Calendar** directly on iOS 17 and earlier).

3. Tap **Calendar Accounts** (or **Accounts**).

4. Tap **Add Account**, then select **Other**.

5. Under the *Calendars* section, tap **Add Subscribed Calendar**.

6. In the **Server** field, paste:

   ```text
   https://ecu-hockey-api.onrender.com/calendar.ics
   ```

7. Tap **Next** in the top right corner. iOS will verify the calendar feed.

8. Set the **Description** to `ECU Men's Ice Hockey Schedule` (this will usually populate automatically). Leave *Username* and *Password* blank, leave *Use SSL* turned on, and tap **Save**.

For more details, see [Apple Support: Use iCloud calendar subscriptions](https://support.apple.com/en-us/102301).

### 3.2. Apple Calendar (macOS)

1. Open the **Calendar** application on your Mac.

2. In the menu bar at the top of your screen, click **File** > **New Calendar Subscription…** (or press `Option + Command + S`).

3. In the **Calendar URL** prompt, enter:

   ```text
   webcal://ecu-hockey-api.onrender.com/calendar.ics
   ```

   *(You can also use the HTTPS URL: `https://ecu-hockey-api.onrender.com/calendar.ics`)*

4. Click **Subscribe**.

5. In the calendar configuration window that appears:

   - **Name**: Enter `ECU Men's Ice Hockey Schedule` (pre-filled).
   - **Location**: Choose **iCloud** to sync across all Apple devices connected to your Apple ID, or **On My Mac** for local only.
   - **Auto-refresh**: Change this from *Every week* to **Every hour** (recommended) or **Every day** to ensure timely fixture updates.
   - **Ignore alerts**: Leave unchecked if you want pre-game notifications.

6. Click **OK**.

For more details, see [Apple Support: Subscribe to calendars on Mac](https://support.apple.com/guide/calendar/subscribe-to-calendars-icl1022/mac).

### 3.3. Google Calendar (Web & Mobile)

Google Calendar subscriptions are set up through the web interface and automatically sync to the Google Calendar app on Android and iOS devices.

1. In a web browser, navigate to [Google Calendar](https://calendar.google.com/).

2. In the left-hand sidebar, find the **Other calendars** section.

3. Click the plus (**+**) button next to *Other calendars*, then select **From URL**.

4. In the **URL of calendar** field, paste:

   ```text
   https://ecu-hockey-api.onrender.com/calendar.ics
   ```

5. *(Optional)* Leave *Make the calendar publicly accessible* unchecked.

6. Click **Add calendar**.

7. The calendar will appear under *Other calendars* as **ECU Men's Ice Hockey Schedule**.

8. *(Optional)* Hover over the calendar name in the sidebar, click the three vertical dots (options menu), and select custom display colors (such as ECU Purple or Gold).

> [!NOTE]
> **Google Calendar Refresh Cadence**: Google Calendar fetches external calendar feeds on its own internal background schedule (typically every 8 to 24 hours). If a match is rescheduled, the change may take up to 24 hours to show up in Google Calendar. This is a limitation of Google Calendar's platform, not the ECU Hockey service.

For more details, see [Google Calendar Help: Subscribe to someone's Google Calendar](https://support.google.com/calendar/answer/37100).

### 3.4. Microsoft Outlook (Web & Microsoft 365)

Subscriptions added via Outlook on the web automatically sync across the Outlook desktop app and Outlook mobile apps connected to your Microsoft account.

1. Sign in to [Outlook on the web](https://outlook.live.com/calendar) or Microsoft 365.

2. Click the **Calendar** icon in the left navigation sidebar.

3. In the calendar navigation pane on the left, click **Add calendar**.

4. In the menu that opens, select **Subscribe from web**.

5. In the input box, paste:

   ```text
   https://ecu-hockey-api.onrender.com/calendar.ics
   ```

6. In the **Calendar name** box, type: `ECU Ice Hockey` (or `ECU Men's Ice Hockey Schedule`).

7. Choose a color and charm icon (e.g. hockey sticks, puck, or sports trophy), and select which calendar group to place it in (such as *Other calendars*).

8. Click **Import**.

For more details, see [Microsoft Support: Outlook Help & Learning](https://support.microsoft.com/en-us/outlook).

### 3.5. Microsoft Outlook (Desktop - Windows & Mac)

- **New Outlook for Windows / Outlook for Mac**: Follow the steps in Section 3.4 above by clicking **Add calendar** > **Subscribe from web**.
- **Classic Outlook for Windows**:
  1. Open Outlook and navigate to the **Calendar** view.

  2. On the **Home** tab in the top ribbon, click **Add Calendar** (or **Open Calendar**) > **From Internet…**.

  3. In the dialog box, paste:

     ```text
     https://ecu-hockey-api.onrender.com/calendar.ics
     ```

  4. Click **OK**.

  5. When prompted to confirm adding the internet calendar and subscribing to updates, click **Yes** (or click *Advanced…* to configure custom display names and update limits).

### 3.6. Other Calendar Applications

Any calendar client supporting the RFC 5545 iCalendar standard can subscribe to the feed:

- **Mozilla Thunderbird**: In the Calendar tab, click the plus (**+**) sign next to *Calendars* > select **On the Network** > choose **iCalendar (ICS)** > paste `https://ecu-hockey-api.onrender.com/calendar.ics` > configure name and refresh interval.
- **Fantastical**: Go to **File** > **New Calendar Subscription…** > paste `webcal://ecu-hockey-api.onrender.com/calendar.ics` > select sync options.

## 4. Customizing Your Calendar Feed (Optional Filters)

The calendar service supports optional query parameters that let you customize which matches appear and how reminders trigger. You can append these parameters to the subscription URL before adding it to your calendar app:

| Parameter       | Type    | Default        | Description                                                                              |
| :-------------- | :------ | :------------- | :--------------------------------------------------------------------------------------- |
| `season`        | string  | Current season | Filter fixtures to a specific academic season (e.g. `?season=2026-2027`).                |
| `include_past`  | boolean | `true`         | Set to `false` to include only upcoming matches and hide past completed games.           |
| `alarm_minutes` | integer | `60`           | Lead time in minutes for reminder alarms before puck drop. Set to `0` to disable alarms. |

### 4.1. Show Only Upcoming Matches (`include_past=false`)

If you want a clean calendar that only shows upcoming games and hides completed matches from earlier in the season:

```text
https://ecu-hockey-api.onrender.com/calendar.ics?include_past=false
```

### 4.2. Custom Reminder Alarms (`alarm_minutes=`)

By default, games include a 60-minute reminder alarm before puck drop. You can customize this alarm offset:

- **2-hour advance reminder**:

  ```text
  https://ecu-hockey-api.onrender.com/calendar.ics?alarm_minutes=120
  ```

- **30-minute reminder**:

  ```text
  https://ecu-hockey-api.onrender.com/calendar.ics?alarm_minutes=30
  ```

- **Disable reminder alarms completely**:

  ```text
  https://ecu-hockey-api.onrender.com/calendar.ics?alarm_minutes=0
  ```

### 4.3. Specific Season Filter (`season=`)

Filter fixtures to an explicit season identifier:

```text
https://ecu-hockey-api.onrender.com/calendar.ics?season=2026-2027
```

### 4.4. Combining Filters

You can combine multiple filters with `&`. For example, to subscribe to upcoming games only with a 2-hour pre-game reminder:

```text
https://ecu-hockey-api.onrender.com/calendar.ics?include_past=false&alarm_minutes=120
```

On macOS or iOS, prepend `webcal://` or use the redirect parameter:

```text
https://ecu-hockey-api.onrender.com/calendar.ics?include_past=false&alarm_minutes=120&webcal=true
```

## 5. Frequently Asked Questions & Troubleshooting

### 5.1. Why did the initial subscription take 30 to 60 seconds to connect?

The ECU Hockey service runs on Render's cloud platform. To conserve compute resources, the free-tier service enters a dormant state after 15 minutes of inactivity. When a calendar client issues a request to a dormant service, Render automatically spins up the application, which takes approximately 50–60 seconds on the first request ("cold start"). Subsequent requests respond in milliseconds.

If your calendar client times out on the initial subscription attempt, simply wait one minute and retry, or open [`https://ecu-hockey-api.onrender.com/health`](https://ecu-hockey-api.onrender.com/health) in your browser first to warm up the server.

### 5.2. How often does the calendar refresh?

The calendar feed advertises RFC 5545 refresh hints (`REFRESH-INTERVAL;VALUE=DURATION:PT1H` and `X-PUBLISHED-TTL:PT1H`), requesting that calendar apps poll every hour.

However, each vendor decides its own refresh frequency:

- **Apple Calendar**: User-configurable. In calendar settings, you can choose **Every hour** (recommended) or **Every day**.
- **Microsoft Outlook**: Typically refreshes every 3 to 4 hours.
- **Google Calendar**: Google controls feed crawling globally on its servers. Feeds typically update every 8 to 24 hours.

### 5.3. Can I edit, reschedule, or delete games directly in my calendar app?

Subscribed calendars are **read-only**. You cannot manually change puck drop times, edit venue notes, or delete individual games within your calendar app because the app continuously syncs with the canonical server feed.

If a game time changes or an opponent changes, the official ingestion worker detects the update and synchronizes it automatically to your subscribed calendar.

### 5.4. How do time zones work?

All matches are published with standard RFC 5545 `VTIMEZONE` metadata for `America/New_York` (Eastern Time). When added to your calendar, your app will automatically translate puck drop times into your device's current local time zone and handle Daylight Saving Time transitions automatically.

### 5.5. How do I unsubscribe or remove the schedule?

You can remove the calendar at any time:

- **Google Calendar**: Go to Settings > *Settings for other calendars* > select *ECU Men's Ice Hockey Schedule* > scroll to the bottom > click **Unsubscribe**.
- **Apple Calendar (Mac)**: Right-click (or `Control`-click) the calendar in the left sidebar > click **Unsubscribe**.
- **Apple Calendar (iOS)**: Open **Settings** > **Apps** > **Calendar** > **Accounts** > **Subscribed Calendars** > tap *ECU Men's Ice Hockey Schedule* > tap **Delete Account**.
- **Outlook**: Right-click the calendar name in your calendar sidebar > select **Delete calendar** or **Remove**.

## 6. Local Development & Contributor Subscriptions

If you are developing or contributing to the `ecu-hockey-calendar` codebase, you can test subscriptions against a local development server.

### 6.1. Running the Local Calendar Service

Start the local API service:

```bash
# Using the CLI
ecu-hockey serve --port 8000

# Or using Uvicorn directly
uv run uvicorn ecu_hockey_calendar.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Once running, the development feed is accessible at:

- **HTTP**: `http://localhost:8000/calendar.ics`
- **Webcal**: `webcal://localhost:8000/calendar.ics`

### 6.2. Local Subscription Limitations

When testing subscriptions locally, keep the following constraints in mind:

- **Cloud Calendar Clients**: Web-based clients like **Google Calendar** and **Outlook on the web** run in remote cloud datacenters. They cannot reach `localhost`, `127.0.0.1`, or private local network IP addresses.
- **Desktop Security Restrictions**: Modern versions of Apple Calendar and Microsoft Outlook often reject non-HTTPS URLs or require valid SSL/TLS certificates when subscribing to internet calendars.

### 6.3. Recommended Workarounds for Testing

To test the calendar feed locally without a public production server:

1. **Static File Import**: Download the `.ics` file directly and import it into your calendar client as a local file:

   ```bash
   curl -s http://127.0.0.1:8000/calendar.ics -o local_schedule.ics
   ```

   Then open your calendar app and choose **File** > **Import…**.

2. **Temporary HTTPS Tunnel**: Expose your local port 8000 through a secure tunnel using tools like [ngrok](https://ngrok.com/) or [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

   ```bash
   ngrok http 8000
   ```

   Copy the generated HTTPS forwarding URL (e.g. `https://xxxx-xx.ngrok-free.app/calendar.ics`) and paste it into Google Calendar or Apple Calendar.
