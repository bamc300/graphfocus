<?php
namespace App\Service;

use App\Repo\UserRepo;
use App\Entity\User;

interface UserRepository {
    public function find(int $id): ?User;
    public function save(User $user): User;
}

class BaseService {
    protected function log(string $msg): void {}
}

class UserService extends BaseService implements UserRepository {
    private UserRepo $repo;

    public function __construct(UserRepo $repo) {
        $this->repo = $repo;
    }

    public function find(int $id): ?User {
        return $this->repo->find($id);
    }

    public function save(User $user): User {
        $this->log("saving");
        return $this->repo->save($user);
    }
}

function plainHelper(int $a, int $b): int {
    return $a + $b;
}
