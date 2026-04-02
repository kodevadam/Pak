/* structs_methods.c - Phase 3 milestone test: impl block detection */

typedef struct {
    float x, y;
} Vec2;

void vec2_init(Vec2 *self, float x, float y) {
    self->x = x;
    self->y = y;
}

Vec2 vec2_add(Vec2 *self, Vec2 other) {
    Vec2 result;
    result.x = self->x + other.x;
    result.y = self->y + other.y;
    return result;
}

float vec2_length(const Vec2 *self) {
    return self->x * self->x + self->y * self->y;
}

void vec2_scale(Vec2 *self, float s) {
    self->x *= s;
    self->y *= s;
}

typedef struct {
    Vec2 pos;
    Vec2 vel;
    int hp;
    int score;
} Player;

void player_init(Player *p, float x, float y) {
    vec2_init(&p->pos, x, y);
    vec2_init(&p->vel, 0.0f, 0.0f);
    p->hp = 100;
    p->score = 0;
}

void player_take_damage(Player *p, int dmg) {
    p->hp -= dmg;
    if (p->hp < 0) p->hp = 0;
}

int player_is_alive(const Player *p) {
    return p->hp > 0;
}

void player_add_score(Player *p, int pts) {
    p->score += pts;
}
