#include <stdio.h>
#include <stdlib.h>
#include "user.h"

typedef struct {
    int id;
    char name[64];
    char email[128];
} User;

struct Point {
    int x;
    int y;
};

int find_user(int id) {
    return id;
}

User* create_user(const char* name) {
    User* u = (User*)malloc(sizeof(User));
    return u;
}

int main(int argc, char** argv) {
    int id = find_user(1);
    User* u = create_user("alice");
    printf("user id=%d\n", id);
    return 0;
}
