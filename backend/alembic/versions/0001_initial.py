"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

category = sa.Enum("men", "women", name="category")
tournament_status = sa.Enum("draft", "locked", "completed", name="tournamentstatus")
match_status = sa.Enum("pending", "in_progress", "completed", name="matchstatus")


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("college_branch", sa.String(200)),
        sa.Column("email", sa.String(200)),
        sa.Column("phone_raw", sa.String(50), nullable=False),
        sa.Column("phone_normalized", sa.String(20), nullable=False),
        sa.Column("states_nationals", sa.String(50)),
        sa.Column("category", category, nullable=False),
        sa.Column("entry_timestamp", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("phone_normalized", "category", name="uq_player_phone_category"),
    )
    op.create_index("ix_players_phone_normalized", "players", ["phone_normalized"])
    op.create_index("ix_players_category", "players", ["category"])

    op.create_table(
        "tournaments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", category, nullable=False, unique=True),
        sa.Column("status", tournament_status, nullable=False),
        sa.Column("draw_seed", sa.Integer()),
        sa.Column("bracket_size", sa.Integer()),
        sa.Column("num_byes", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("position_in_round", sa.Integer(), nullable=False),
        sa.Column("player_a_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("player_b_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("is_bye", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("winner_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("retired_player_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("next_match_id", sa.Integer(), sa.ForeignKey("matches.id")),
        sa.Column("status", match_status, nullable=False),
    )
    op.create_index("ix_matches_tournament_id", "matches", ["tournament_id"])

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_number", sa.Integer(), nullable=False),
        sa.Column("score_a", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_b", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_games_match_id", "games", ["match_id"])

    op.create_table(
        "round_formats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_number", sa.Integer()),
        sa.Column("points_to_win", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("win_by_two", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hard_cap", sa.Integer()),
        sa.Column("games_to_win_match", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tournament_id", "round_number", name="uq_format_tournament_round"),
    )
    op.create_index("ix_round_formats_tournament_id", "round_formats", ["tournament_id"])

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("added_by", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_email", sa.String(200), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("admins")
    op.drop_index("ix_round_formats_tournament_id", "round_formats")
    op.drop_table("round_formats")
    op.drop_index("ix_games_match_id", "games")
    op.drop_table("games")
    op.drop_index("ix_matches_tournament_id", "matches")
    op.drop_table("matches")
    op.drop_table("tournaments")
    op.drop_index("ix_players_category", "players")
    op.drop_index("ix_players_phone_normalized", "players")
    op.drop_table("players")
    match_status.drop(op.get_bind(), checkfirst=True)
    tournament_status.drop(op.get_bind(), checkfirst=True)
    category.drop(op.get_bind(), checkfirst=True)
