package com.example.svc

import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

interface UserRepository {
    fun findById(id: String): User?
    fun save(user: User): User
}

data class User(val id: String, val name: String)

@Service
class UserService(private val repo: UserRepository) {

    @Transactional
    fun create(name: String): User {
        val u = User(id = "x", name = name)
        return repo.save(u)
    }

    fun find(id: String): User? = repo.findById(id)
}

object Constants {
    const val DEFAULT_PAGE_SIZE = 20
}

fun topLevelHelper(a: Int, b: Int): Int = a + b
