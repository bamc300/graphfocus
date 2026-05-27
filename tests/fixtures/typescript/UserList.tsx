import React, { useState, useEffect } from "react";
import { fetchUsers } from "./api";

interface User {
  id: string;
  name: string;
}

type UserListProps = {
  pageSize: number;
};

export function UserList({ pageSize }: UserListProps) {
  const [users, setUsers] = useState<User[]>([]);

  useEffect(() => {
    fetchUsers(pageSize).then(setUsers);
  }, [pageSize]);

  return (
    <ul>
      {users.map((u) => (
        <li key={u.id}>{u.name}</li>
      ))}
    </ul>
  );
}

export const UserBadge = ({ name }: { name: string }) => <span>{name}</span>;

export class UserDashboard extends React.Component<UserListProps> {
  render() {
    return <UserList pageSize={10} />;
  }
}

export function plainHelper(a: number, b: number): number {
  return a + b;
}
