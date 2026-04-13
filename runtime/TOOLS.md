# Tool Usage Hints — TOOLS.md

## Tool Selection Guide

| User Intent      | Best Tool          | Input Example                              |
| ---------------- | ------------------ | ------------------------------------------ |
| Math calculation | `calculator`       | `sqrt(144) + 2**10`                        |
| Current weather  | `weather_lookup`   | `Tokyo`                                    |
| Web search       | `web_search`       | `python async tutorial 2026`               |
| Wikipedia facts  | `wikipedia_lookup` | `Alan Turing`                              |
| Read a web page  | `url_fetcher`      | `https://example.com`                      |
| Unit conversion  | `unit_converter`   | `100 km to miles`                          |
| File operations  | `file_manager`     | `list .` or `read config.py`               |
| System info      | `system_info`      | (empty string)                             |
| Text analysis    | `text_analyzer`    | `<the text to analyze>`                    |
| Hash/encode      | `hash_encode`      | `sha256 hello world`                       |
| IP geolocation   | `ip_lookup`        | `8.8.8.8` or empty for own IP              |
| Notes            | `note_taker`       | `save remember to buy milk`                |
| OCR documents    | `document_ocr`     | `scan photo.png`                           |
| JSON/YAML        | `json_yaml_tool`   | `format {"key":"value"}`                   |
| CSV data         | `csv_data_tool`    | `parse name,age\nAlice,30`                 |
| PDF reading      | `pdf_reader`       | `read document.pdf`                        |
| Run Python code  | `code_runner`      | `print("hello")`                           |
| Process list     | `process_manager`  | `top` or `search python`                   |
| Network check    | `network_diag`     | `ping google.com`                          |
| Password gen     | `password_gen`     | `strong 24`                                |
| Regex test       | `regex_tool`       | `test \d+ abc123`                          |
| Archive files    | `archive_tool`     | `list backup.zip`                          |
| Currency convert | `currency_convert` | `100 USD to EUR`                           |
| Schedule tasks   | `schedule_tool`    | `add daily-weather every 6h Check weather` |

## Tips

- For `calculator`: use Python math syntax. Available: `sqrt`, `sin`, `cos`, `factorial`, `pi`, `e`, `log`, `log10`.
- For `weather_lookup`: just pass the city name, not "weather in London".
- For `web_search`: be specific. "best python web framework 2026" > "python".
- For `file_manager`: prefix with action: `read`, `write`, `list`, `append`, `info`.
- For `schedule_tool`: intervals are `every 30m`, `every 2h`, `daily HH:MM`, `weekly DAY HH:MM`. Use `list` to see active tasks. Edit `runtime/HEARTBEAT.md` for persistent system-level tasks.
