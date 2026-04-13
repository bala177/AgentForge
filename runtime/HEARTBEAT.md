# Heartbeat Tasks — HEARTBEAT.md

<!--
  Define scheduled background tasks here.
  The agent will execute these prompts periodically (default: every 30 minutes).

  Format:
    ## task-name
    schedule: every 30m | daily HH:MM | weekly DAY HH:MM
    > The prompt to send to the agent

  Tasks are parsed at each heartbeat tick. Edit this file anytime — no restart needed.
  Set HEARTBEAT_INTERVAL_SECS env var to change the interval (default: 1800 = 30 min).

  EXAMPLES (uncomment to activate):
-->

<!--
## daily-summary
schedule: daily 08:00
> Review yesterday's activity journal entries. Create a concise summary note
> with the tag "daily-summary".

## proactive-memory
schedule: every 30m
> Review the 10 most recent conversation messages. Extract any new user
> preferences or facts worth remembering. Save them using the note_taker tool.

## weather-check
schedule: every 6h
> Check the weather for the user's city (from USER.md). If rain or storms
> are forecast, save a note with tag "weather-alert".
-->
