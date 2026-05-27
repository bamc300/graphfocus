import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'models.dart';

abstract class Repository {
  Future<User?> find(String id);
  Future<void> save(User user);
}

class HttpRepository implements Repository {
  final Dio client;

  HttpRepository(this.client);

  @override
  Future<User?> find(String id) async {
    final response = await client.get('/users/$id');
    return User.fromJson(response.data);
  }

  @override
  Future<void> save(User user) async {
    await client.post('/users', data: user.toJson());
  }
}

class UserService {
  final Repository repo;
  UserService(this.repo);

  Future<User?> find(String id) => repo.find(id);
}

mixin Loggable {
  void log(String msg) => print(msg);
}

int helper(int a, int b) {
  return a + b;
}
