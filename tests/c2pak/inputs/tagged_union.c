/* tagged_union.c - Phase 3 milestone test: tagged union → variant */

typedef struct { float x, y; } Vec2;

typedef enum {
    ENTITY_PLAYER,
    ENTITY_ENEMY,
    ENTITY_COIN,
    ENTITY_NONE
} EntityType;

typedef struct {
    EntityType type;
    Vec2 pos;
    union {
        struct { int hp; int mp; } player;
        struct { int hp; unsigned char ai_state; } enemy;
        struct { int value; } coin;
    };
} Entity;

void entity_update(Entity *e) {
    switch (e->type) {
        case ENTITY_PLAYER:
            e->player.hp -= 1;
            break;
        case ENTITY_ENEMY:
            e->enemy.ai_state = 1;
            break;
        case ENTITY_COIN:
            break;
        case ENTITY_NONE:
            break;
    }
}

int entity_is_alive(const Entity *e) {
    switch (e->type) {
        case ENTITY_PLAYER:
            return e->player.hp > 0;
        case ENTITY_ENEMY:
            return e->enemy.hp > 0;
        default:
            return 0;
    }
}
