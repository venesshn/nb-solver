# Naruto Blazing Mission Solver

Live site: https://venesshn.github.io/nb-solver/

Pick a Naruto Blazing mission, load your own box (upload a screen recording of
your unit pages, or add units by hand), and get the team that clears it most
easily, a turn-by-turn plan on an animated grid, and an honest clear
likelihood. Everything runs in your browser; nothing is uploaded.

It is a preview: the simulator's assumptions are listed on every result.

## Development

```
uv sync
uv run pytest
uv run python scripts/solve.py e3003 "The Evil Snake Shows its Fangs [B]"
uv run python scripts/build_web.py      # writes site/
```

`tools/validate_reader.mjs` checks the in-browser recording reader against
labelled recordings (needs `npm install` in `tools/`).

Fan-made; not affiliated with Bandai Namco. Mission and unit data come from
community projects (blazingonline.wiki, hideoutgacha). No game art is used.
