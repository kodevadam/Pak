/* basic_types.c - Phase 1 milestone test: type mapping and simple declarations */

typedef struct { float x, y; } Vec2;
typedef struct { float x, y, z; } Vec3;

typedef enum {
    DIR_UP,
    DIR_DOWN,
    DIR_LEFT,
    DIR_RIGHT
} Direction;

typedef enum {
    STATE_IDLE = 0,
    STATE_ACTIVE = 1,
    STATE_DEAD = 2
} State;

typedef struct {
    Vec2 pos;
    int hp;
    unsigned char level;
    Direction facing;
    State state;
} Player;

Vec2 vec2_add(Vec2 a, Vec2 b) {
    Vec2 result;
    result.x = a.x + b.x;
    result.y = a.y + b.y;
    return result;
}

int main(void) {
    Vec2 pos = {1.0f, 2.0f};
    Vec2 vel = {0.5f, -0.3f};
    Vec2 new_pos = vec2_add(pos, vel);
    return 0;
}
