#ifndef GAME_H
#define GAME_H
typedef struct { float x, y; } Vec2;
typedef enum { DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT } Direction;
void player_update(Vec2 *p, float dt);
#endif
