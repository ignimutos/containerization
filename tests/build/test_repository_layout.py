from pathlib import Path


EXPECTED = [
    "images/caddy/config.yml",
    "images/naive-client/config.yml",
    "images/naive-server/config.yml",
    "images/nezha-agent/config.yml",
    "images/tg-signer/config.yml",
    "images/tor2socks/config.yml",
]


def test_expected_image_layout_exists() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for relative_path in EXPECTED:
        assert (repo_root / relative_path).exists(), relative_path
