/*
        Написать запрос, который выводит общее число тегов
*/
//use movies
print("tags count: ", db.tags.find().count());
//91106
/*
        Добавляем фильтрацию: считаем только количество тегов Adventure
*/
print("Adventure tags count: ", db.tags.find({tag_name:"Adventure"}).count());
//3496
/*
        Очень сложный запрос: используем группировку данных посчитать количество вхождений для каждого тега
        и напечатать top-3 самых популярных
*/

printjson(
        db.tags.aggregate([
                {"$group": {
                                _id:"$tag_name", 
                                count:{$sum:1}
                           }
                },
                {$sort:{count:-1}},
                {$limit:3}
        ])['_batch']
);
/*
	{
		"_id" : "Thriller",
		"count" : 7624
	},
	{
		"_id" : "Comedy",
		"count" : 13182
	},
	{
		"_id" : "Drama",
		"count" : 20265
        }
*/
