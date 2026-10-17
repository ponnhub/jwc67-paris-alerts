# jwc67-paris-alerts

แจ้งเตือนสดสำหรับนักท่องเที่ยวไทยในปารีส ใช้ในแอป [jwc67-paris.web.app](https://jwc67-paris.web.app)
Live Paris alerts feed for the jwc67-paris traveler app.

**อัปเดตอัตโนมัติทุกชั่วโมง / auto-updated hourly** → [`alerts.json`](alerts.json)
Raw URL: `https://raw.githubusercontent.com/ponnhub/jwc67-paris-alerts/main/alerts.json`

## เนื้อหา / What it covers
ชุมนุม/ประท้วง · นัดหยุดงาน RATP/SNCF · สถานีหรือสายเมโทร/RER ปิด · ปิดถนน/จราจร · สถานที่ท่องเที่ยวปิด (Louvre, Eiffel, Orsay, Versailles) · การเมือง · ความปลอดภัย
Protests, RATP/SNCF strikes, station/line closures, road closures, sight closures, politics, safety incidents.

## แหล่งข้อมูล / Sources
- Google News RSS (ค้นหาภาษาฝรั่งเศสและอังกฤษ / FR + EN queries), linking to the original publisher
- BFM Paris RSS — https://www.bfmtv.com/rss/paris/
- France 24 RSS — https://www.france24.com/fr/france/rss
- franceinfo RSS — https://www.francetvinfo.fr/titres.rss
- Île-de-France Mobilités PRIM (official line reports, only when `PRIM_API_KEY` is configured)

## กติกา / Rules
- ไม่แต่งข่าว ทุกรายการคือหัวข่าวจริงพร้อมลิงก์ต้นทาง / Nothing invented: every item is a real headline with its source link.
- เก็บเฉพาะข่าว 72 ชม. ล่าสุด หรือข่าวประกาศล่วงหน้า (เช่นนัดหยุดงาน) ไม่เกิน 7 วัน / Last 72 h, or announcements of upcoming events up to 7 days old. Duplicates removed.
- ข้อความไทย (`title_th`, `summary_th`) เป็นป้ายสรุปตามคำสำคัญ ไม่ใช่คำแปล โปรดกดอ่านต้นทาง / Thai text is a keyword-based label, not a translation. Read the source.
- `time` = เวลาปารีส (Europe/Paris), `time_th` = เวลาไทย (Asia/Bangkok)

## Schema (v2)
```json
{"schema":2,"updated_at":"…+02:00","updated_at_th":"…+07:00","count":N,
 "items":[{"id","cat","cat_th","severity","title_th","summary_th","title","lang",
           "src","src_home","url","time","time_th","event_date","upcoming","via"}]}
```

## Run
```
python3 build_alerts.py            # build alerts.json
python3 build_alerts.py --push     # build + push if changed (needs GITHUB_ALERTS_TOKEN)
```
Data © the respective publishers; headlines are quoted with links for information only.
