use std::collections::HashMap;

pub struct User {
    pub id: String,
    pub name: String,
}

pub trait Repository {
    fn find(&self, id: &str) -> Option<User>;
    fn save(&mut self, user: User);
}

pub struct InMemoryRepo {
    storage: HashMap<String, User>,
}

impl InMemoryRepo {
    pub fn new() -> Self {
        InMemoryRepo { storage: HashMap::new() }
    }
}

impl Repository for InMemoryRepo {
    fn find(&self, id: &str) -> Option<User> {
        self.storage.get(id).cloned().map(|u| User { id: u.id, name: u.name })
    }
    fn save(&mut self, user: User) {
        self.storage.insert(user.id.clone(), user);
    }
}

pub enum Role {
    Admin,
    Member,
}

pub fn plain_helper(a: i32, b: i32) -> i32 {
    a + b
}
