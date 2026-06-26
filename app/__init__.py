"""Job-matching dashboard application built on top of the jobspy library.

Pipeline: scrape (Indeed + LinkedIn, UK) -> dedup by jobspy id -> store as
`pending` -> match each pending job via OpenAI -> `matched`/`rejected`.
"""
