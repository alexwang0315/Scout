from pathlib import Path

from scout_env import load_scout_env_files


def test_scout_env_loader_prefers_shell_then_repo_then_persistent(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    persistent_env = tmp_path / "persistent.env"
    (repo_root / ".env").write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=sk-repo-should-not-win",
                "export CWA_API_KEY='cwa-from-repo'",
            ]
        ),
        encoding="utf-8",
    )
    persistent_env.write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=sk-persistent-should-not-win",
                'SCOUT_CWA_API_KEY="scout-cwa-from-persistent"',
            ]
        ),
        encoding="utf-8",
    )
    environ = {"OPENROUTER_API_KEY": "sk-shell-wins"}

    result = load_scout_env_files(
        repo_root=repo_root,
        persistent_env_file=persistent_env,
        environ=environ,
    )

    assert environ["OPENROUTER_API_KEY"] == "sk-shell-wins"
    assert environ["CWA_API_KEY"] == "cwa-from-repo"
    assert environ["SCOUT_CWA_API_KEY"] == "scout-cwa-from-persistent"
    assert result.credential_values_exposed is False
    assert "sk-shell-wins" not in str(result)
    assert "cwa-from-repo" not in str(result)
    assert result.loaded_files == (str(repo_root / ".env"), str(persistent_env))


def test_scout_env_loader_uses_persistent_when_repo_key_is_absent(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    persistent_env = tmp_path / "persistent.env"
    persistent_env.write_text("OPENROUTER_API_KEY=sk-from-persistent\n", encoding="utf-8")
    environ: dict[str, str] = {}

    result = load_scout_env_files(
        repo_root=repo_root,
        persistent_env_file=persistent_env,
        environ=environ,
    )

    assert environ["OPENROUTER_API_KEY"] == "sk-from-persistent"
    assert result.loaded_keys == ("OPENROUTER_API_KEY",)
    assert "sk-from-persistent" not in str(result)
