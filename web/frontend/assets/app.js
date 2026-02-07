const { createApp, ref, onMounted, reactive } = Vue;

createApp({
    setup() {
        const teachers = ref([]);
        const isEditing = ref(false);
        const isSaving = ref(false);
        const isUploading = ref(false);
        const downloadLink = ref(null);
        const toasts = ref([]);
        
        const initialForm = {
            id: null,
            short_name: '',
            full_name: '',
            position: '',
            rank: '',
            academic_degree: ''
        };

        const form = reactive({ ...initialForm });

        // Notifications
        const addToast = (title, message, type = 'info') => {
            toasts.value.push({ title, message, type });
            setTimeout(() => {
                removeToast(0);
            }, 5000);
        };

        const removeToast = (index) => {
            toasts.value.splice(index, 1);
        };

        // Fetch all teachers
        const fetchTeachers = async () => {
            try {
                const response = await axios.get('/api/teachers');
                teachers.value = response.data;
            } catch (error) {
                addToast('Ошибка', 'Не удалось загрузить список преподавателей', 'error');
                console.error(error);
            }
        };

        // Save teacher (Create or Update)
        const saveTeacher = async () => {
            isSaving.value = true;
            try {
                if (isEditing.value) {
                    await axios.put(`/api/teachers/${form.id}`, form);
                    addToast('Успех', 'Данные преподавателя обновлены');
                } else {
                    await axios.post('/api/teachers', form);
                    addToast('Успех', 'Преподаватель добавлен');
                }
                resetForm();
                await fetchTeachers();
            } catch (error) {
                addToast('Ошибка', 'Не удалось сохранить данные', 'error');
                console.error(error);
            } finally {
                isSaving.value = false;
            }
        };

        // Edit teacher
        const editTeacher = (teacher) => {
            isEditing.value = true;
            Object.assign(form, teacher);
        };

        // Delete teacher
        const deleteTeacher = async (id) => {
            if (!confirm('Вы уверены, что хотите удалить этого преподавателя?')) return;
            
            try {
                await axios.delete(`/api/teachers/${id}`);
                addToast('Удалено', 'Преподаватель удален из базы');
                await fetchTeachers();
            } catch (error) {
                addToast('Ошибка', 'Не удалось удалить преподавателя', 'error');
            }
        };

        const resetForm = () => {
            isEditing.value = false;
            Object.assign(form, initialForm);
        };

        // File Upload and Schedule Generation
        const handleFileUpload = async (event) => {
            const file = event.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            isUploading.value = true;
            downloadLink.value = null;

            try {
                const response = await axios.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                
                if (response.data.status === 'success') {
                    // We assume there's a route to serve files from output directory
                    // If not, we'd need to add one. For now, we point to the API.
                    downloadLink.value = `/api/download/${response.data.filename}`;
                    addToast('Готово', 'Расписание успешно сформировано');
                }
            } catch (error) {
                const errorMsg = error.response?.data?.detail || 'Произошла ошибка при обработке файла';
                addToast('Ошибка', errorMsg, 'error');
                console.error(error);
            } finally {
                isUploading.value = false;
                // Clear input
                event.target.value = '';
            }
        };

        onMounted(fetchTeachers);

        return {
            teachers,
            form,
            isEditing,
            isSaving,
            isUploading,
            downloadLink,
            toasts,
            saveTeacher,
            editTeacher,
            deleteTeacher,
            resetForm,
            handleFileUpload,
            removeToast
        };
    }
}).mount('#app');
