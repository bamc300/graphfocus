<template>
  <section class="user-list">
    <h2>Users</h2>
    <UserCard v-for="u in users" :key="u.id" :user="u" />
    <user-badge :name="title" />
    <button @click="reload">Reload</button>
  </section>
</template>

<script lang="ts">
import { defineComponent, ref, onMounted } from "vue";
import { fetchUsers } from "./api";

interface User {
  id: string;
  name: string;
}

export default defineComponent({
  name: "UserList",
  props: {
    title: { type: String, required: true },
  },
  setup() {
    const users = ref<User[]>([]);

    function reload() {
      fetchUsers().then((data) => {
        users.value = data;
      });
    }

    onMounted(reload);

    return { users, reload };
  },
});
</script>

<style scoped>
.user-list { padding: 1rem; }
</style>
