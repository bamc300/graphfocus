import Foundation
import Combine

protocol UserRepository {
    func find(id: String) -> User?
    func save(user: User)
}

struct User {
    let id: String
    let name: String
}

enum Role {
    case admin
    case member
}

class UserService {
    let repo: UserRepository

    init(repo: UserRepository) {
        self.repo = repo
    }

    func find(id: String) -> User? {
        return repo.find(id: id)
    }

    func create(name: String) -> User {
        let user = User(id: UUID().uuidString, name: name)
        repo.save(user: user)
        return user
    }
}

func plainHelper(_ a: Int, _ b: Int) -> Int {
    return a + b
}
