package com.example.service;

import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserService {

    private final UserRepository repository;

    public UserService(UserRepository repository) {
        this.repository = repository;
    }

    public Optional<User> findById(UUID id) {
        return repository.findByIdAndIsDeletedIsFalse(id);
    }

    @Transactional
    public User create(User user, String createdBy) {
        if (user.getId() != null) {
            throw new UnsupportedOperationException("ID must be null for creation");
        }
        validateUser(user);
        return repository.save(user);
    }

    @Transactional
    public User update(User user, String modifiedBy) {
        if (user.getId() == null) {
            throw new UnsupportedOperationException("ID must not be null for update");
        }
        return repository.save(user);
    }

    private void validateUser(User user) {
        if (user.getName() == null || user.getName().isBlank()) {
            throw new IllegalArgumentException("Name is required");
        }
    }
}
