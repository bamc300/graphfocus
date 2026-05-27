package com.example.svc

import scala.collection.mutable
import org.example.User

trait UserRepository {
  def find(id: String): Option[User]
  def save(user: User): User
}

case class User(id: String, name: String)

class UserService(repo: UserRepository) {
  def find(id: String): Option[User] = repo.find(id)

  def create(name: String): User = {
    val u = User(id = "x", name = name)
    repo.save(u)
  }
}

object Constants {
  val PAGE_SIZE = 20
  def helper(a: Int, b: Int): Int = a + b
}
