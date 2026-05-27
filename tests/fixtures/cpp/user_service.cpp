#include <string>
#include <memory>
#include "repository.hpp"

namespace app {

class User {
public:
    std::string id;
    std::string name;
};

class BaseService {
public:
    virtual ~BaseService() = default;
    void log(const std::string& msg);
};

class UserService : public BaseService {
public:
    UserService(std::shared_ptr<Repository> repo);
    User find(int id);
    User create(const std::string& name);
private:
    std::shared_ptr<Repository> repo_;
};

UserService::UserService(std::shared_ptr<Repository> repo) : repo_(repo) {}

User UserService::find(int id) {
    return repo_->find(id);
}

User UserService::create(const std::string& name) {
    log("creating");
    return User{};
}

int helper(int a, int b) {
    return a + b;
}

}  // namespace app
